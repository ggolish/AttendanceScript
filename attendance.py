#!/usr/bin/env python3

from subprocess import getoutput
import json
import os
import sys
import datetime
import argparse
import resource

# Global datetime when program is ran
today = datetime.datetime.today()

# Used to convert dstring config variable to weekday
days = {"m": 0, "t": 1, "w": 2, "r": 3, "f": 4}

# Global list of names mapping to student login
names = {}

# Keeps track of students who forgot to log out
still_logged_in = {}

# Takes a date string of the format "%b %d %H:%M" and returns it as a datetime object
# e.g. "Aug 22 11:50" NOTE: using the year of todays date will not cause a problem because
# semesters do not span more than one year for a given class
def make_date(s):
    global today
    return datetime.datetime.strptime(s, "%b %d %H:%M").replace(year=today.year)

# Loads the config file from the current directory
def load_config():
    with open(".attendance", "r") as fd:
        config = json.load(fd)

    # Ensure all fields are present in config map
    required = ["start_time", "end_time", "class_no", "machine_no", "dstring", "start_day"]
    for f in required:
        if f not in config:
            sys.stderr.write(f"Error: Config file must contain field '{f}'")
            sys.exit(1)

    # Set default values for optional config fields
    if "ignore" not in config:
        config["ignore"] = []
    if "everyone" not in config:
        config["everyone"] = False
    if "ignore_dates" not in config:
        config["ignore_dates"] = []

    return config
       
# Takes the ellapsed time string from last and returns the ammount of time in days, minutes, and
# hours
def parse_ellapsed_time(s):
    days = 0
    hours = 0
    minutes = 0
    # Remove parentheses
    s = s[1:-1]
    # If there is a '+' in the string, it has a days portion
    if '+' in s:
        li = s.split('+')
        days = int(li[0])
        s = ':'.join(li[1:])
    hours, minutes = map(int, s.split(':'))
    return (days, hours, minutes)

# Given the username of the account, returns the name in /etc/passwd
def get_name(username):
    global names
    if username in names:
        return names[username]
    line = getoutput("grep '^{}' /etc/passwd".format(username))
    name = line.split(':')[4].split(',')[0]
    names[username] = name
    return name

# Given the machine prefix and the course number, return the results of the
# last commmand on each machine
def get_last(m_no, c_no, verbose=True):
    # Set the resource limit of the process to prevent dsh from hanging
    resource.setrlimit(resource.RLIMIT_NPROC, (500, 500))
    # Using distributed shell to collect last data from each machine
    output = getoutput("dsh -f -N {} -e 'last | grep ^{}'".format(
        m_no, c_no.replace("[", "\[").replace("]", "\]")))
    # Skip the first line from dsh, not needed
    li = output.split("\n")
    while not li[0].startswith("executing"): 
        print(li[0])
        li.pop(0)
    # Format each line so that the hostname is moved to the end of the line
    for i in range(1, len(li)):
        p = li[i].split(":")
        rest = ":".join(p[1:]).lstrip()
        li[i] = " ".join([rest, p[0]])
    return li

def get_who(m_no, c_no):
    # Set the resource limit of the process to prevent dsh from hanging
    # Using distributed shell to collect who data from each machine
    output = getoutput("dsh -f -N {} -e 'who | grep ^{}'".format(
        m_no, c_no.replace("[", "\[").replace("]", "\]")))
    # Skip the first line from dsh, not needed
    li = output.split("\n")
    while not li[0].startswith("executing"): 
        sys.stderr.write("{}\n".format(li[0]))
        li.pop(0)
    return set((get_name(l.split()[1]), l.split()[1]) for l in li[1:])


# Extracts students and most recent logins from last output lines, remote connections
# are ommitted
def extract_students(lines):
    students = []
    for line in lines:
        li = line.split()
        # If the second field in the line starts with a ':', the login is local
        if li[1][0] == ":":
            start = make_date(' '.join(li[3:6]))
            if li[6] == "still":
                end = None
            else:
                delta = parse_ellapsed_time(li[-2])
                end = start + datetime.timedelta(days=delta[0], hours=delta[1],
                                                minutes=delta[2])
            students.append({"start": start, "end": end, "name": get_name(li[0]), "login": li[0], "og": line, "machine": li[-1]})
    return students

# Determines if a student is logged in during a given date range
def student_logged_in(s, start_date, end_date):
    global still_logged_in
    # A student must login / logout +-15 minutes of class time
    delta = datetime.timedelta(minutes=15)
    st = start_date - delta
    et = end_date + delta
    # Check the cases where the student is still logged in
    if s["end"] == None:
        # If the student is still logged in, save for later
        if s["name"] not in still_logged_in:
            still_logged_in[s["name"]] = s
        if s["start"] >= st and s["start"] <= et:
            return True
        return False
    # Check the cases where the student is no longer logged in
    if s["start"] >= st and s["start"] <= et:
        return True
    if s["end"] >= st and s["end"] <= et:
        return True
    # The logged in time frame does not overlap with the specified time frame
    return False

# Takes the list of students' logins and filters out those who were not logged
# in during the specified range
def filter_by_date(students, start_date, end_date):
    return [s for s in students if student_logged_in(s, start_date, end_date)]

# Return all name, login pairs for class
def get_all_names(class_no, everyone=False):
    lines = getoutput("grep '^{}' /etc/passwd".format(class_no)).split("\n")
    names = []
    for line in lines:
        pieces = line.split(":")
        name = pieces[4].split(",")[0]
        if name or everyone:
            names.append((name, pieces[0]))
    return names

def lab_report(config, usernames, start_range, end_range):
    if usernames[0] == "all":
        usernames = [d[1] for d in get_all_names(config["class_no"])]
    logins = extract_students(get_last(config["machine_no"], config["class_no"]))
    logins = filter_by_date(logins, start_range, end_range)
    targets = [s for s in logins if s["login"] in usernames]
    counts = dict((u, [0, 0]) for u in usernames)
    for t in targets:
        counts[t["login"]][0] += 1
        counts[t["login"]][1] += (t["end"] - t["start"]).total_seconds() / 3600

    print("*"*72)
    print("Lab Hours Report {} - {} [{} machines]".format(start_range, end_range, config["machine_no"]))
    print("*"*72)
    print("Username".center(10), "|", "Logins".center(8), "|", "Hours".center(10))
    print("-"*32)
    for u, d in counts.items():
        print("{:10s} | {:8d} | {:8.2f}".format(u, d[0], d[1]))

def roll_call(config):
    who = get_who(config["machine_no"], config["class_no"])
    print("Here:")
    for n, _ in who:
        print(n)
    print()
    print("Absent:")
    for n, u in [n for n in get_all_names(config["class_no"]) if n not in who]:
        if u not in config["ignore"]: print(n)
    print()

def main(config, start_date, end_date, start_range, end_range, args):
    global today, days
    logins = extract_students(get_last(config["machine_no"], config["class_no"], verbose=False))
    curr_start = start_date
    curr_end = end_date
    delta = datetime.timedelta(days=1)
    class_days = [days[c.lower()] for c in config["dstring"]]
    attendance = {}
    for n in get_all_names(config["class_no"], everyone=config["everyone"]):
        if n[1] not in config["ignore"]: attendance[n] = [0, []]
    total = 0
    while curr_end < today:
        if curr_start.weekday() in class_days and curr_start >= start_range and curr_end <= end_range and curr_start not in config["ignore_dates"]:
            total += 1
            curr_logins = filter_by_date(logins, curr_start, curr_end)
            names = list(set([(s["name"], s["login"]) for s in curr_logins]))
            for n in names: 
                if n in attendance:
                    attendance[n][0] += 1
            for n in [n for n in attendance.keys() if n not in names]:
                attendance[n][1].append(curr_start.strftime("%a %b %d"))
        curr_start += delta
        curr_end += delta

    if args.absent:
        print_absent(attendance)
    else:
        print_totals(attendance, total)

def print_totals(attendance, total):
    global today, still_logged_in
    print("*"*50)
    print("Attendance Report as of", today)
    print("*"*50)
    for n, x in attendance.items():
        print("{:30s} {:10s} {:6.2f}%".format(n[0], n[1], x[0] / total * 100))
    if still_logged_in: print("\nStill logged in:")
    for s in still_logged_in.values():
        print("{} ({}) logged in at {} on {}".format(s["name"], s["login"], s["start"], s["machine"]))

def print_absent(attendance):
    print("*"*50)
    print("Absence Report as of", today)
    print("*"*50)
    for n, x in attendance.items():
        if x[1]:
            print("{} ({}):".format(n[0], n[1]))
            for d in x[1]:
                print("- {}".format(d))
            print()

if __name__ == "__main__":
    config = load_config()
    if not config:
        sys.stderr.write("Error: Unable to find config file '.attendance'!\n")
        sys.exit(1)

    parser = argparse.ArgumentParser(prog="attendance", description="Displays the attendance for a course.")
    parser.add_argument("-a", "--absent", action="store_true", help="Display the absence report.")
    parser.add_argument("-s", "--start", help="Specifies the beginning of the date range checked.")
    parser.add_argument("-e", "--end", help="Specifies the end of the date range checked.")
    parser.add_argument("-r", "--roll", action="store_true", help="Displays who is and isn't logged in now.")
    parser.add_argument("-m", "--machine-prefix", type=str, help="Overrides the machine_no specified in config.")
    parser.add_argument("-l", "--lab-report", type=str, help="Display a lab report for given set of users: user1,user2,...")
    args = parser.parse_args(sys.argv[1:])

    if args.machine_prefix:
        config["machine_no"] = args.machine_prefix

    if config["machine_no"] not in ["x", "y", "z"]:
        sys.stderr.write("Error: '{}' is an invalid machine prefix.\n".format(config["machine_no"]))
        sys.exit(1)

    if args.roll:
        roll_call(config)
        sys.exit(0)

    start_date = make_date("{} {}".format(config["start_day"], config["start_time"]))
    end_date = make_date("{} {}".format(config["start_day"], config["end_time"]))

    start_range = datetime.datetime.min
    end_range = datetime.datetime.max

    if args.start:
        start_range = make_date("{} {}".format(args.start, config["start_time"]))
    if args.end:
        end_range = make_date("{} {}".format(args.end, config["end_time"]))

    if args.lab_report:
        if not args.start or not args.end:
            sys.stderr.write("Usage: Please specify <start> and <end> dates for lab report.\n");
            sys.exit(1)
        lab_report(config, args.lab_report.split(","), start_range, end_range)
        sys.exit(0)

    for i in range(len(config["ignore_dates"])):
        config["ignore_dates"][i] = make_date("{} {}".format(config["ignore_dates"][i], config["start_time"]))

    main(config, start_date, end_date, start_range, end_range, args)


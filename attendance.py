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
    try:
        fd = open(".attendance", "r")
    except:
        return {}

    return json.load(fd)
        
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
    resource.setrlimit(resource.RLIMIT_NPROC, (100, 100))
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

def main(config, start_date, end_date, args):
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
        if curr_start.weekday() in class_days:
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
    args = parser.parse_args(sys.argv[1:])

    start_date = make_date("{} {}".format(config["start_day"], config["start_time"]))
    end_date = make_date("{} {}".format(config["start_day"], config["end_time"]))

    main(config, start_date, end_date, args)


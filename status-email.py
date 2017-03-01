import smtplib
import requests
import dateutil.parser
import datetime
import pytz
import sys

try:
    from settings import *
except ImportError:
    print "settings.py missing, copy settings.py.sample and modify values"
    sys.exit(-1)

def get_build_status(version):
    data = requests.get(
        J2_JOB_FORMAT % version,
        auth=(J2_USER, J2_PASSWORD))
    data.raise_for_status()
    json = data.json()
    return {'version': version,
            'started': json['timestamp'],
            'duration': json['duration'],
            'result': json['result'],
            'url': json['url']}


def get_build_status_j1(version):
    data = requests.get(J1_JOB_FORMAT % version)
    data.raise_for_status()
    json = data.json()
    return {'version': version,
            'started': json['timestamp'],
            'duration': json['duration'],
            'result': json['result'],
            'url': json['url']}

def issue_query(query):
    params = {'jql': query, 'fields': 'key,summary,assignee'}
    data = requests.get("%s/rest/api/2/search" % JIRA_URI,
                        params=params, auth=(JIRA_USER, JIRA_PASSWORD))
    data.raise_for_status()

    issues = []
    json = data.json()

    return [{'key': i['key'],
             'summary': i['fields']['summary'],
             'assignee': i['fields']['assignee']['name'] if 'assignee' in i['fields'] and i['fields']['assignee'] else None,
             'url': "%sbrowse/%s" % (JIRA_URI, i['key'])}
            for i in json['issues']]

def critical_issues():
    return issue_query("project = MI AND resolution = Unresolved AND priority = Critical AND status != WaitingForCustomer")

def critical_issues_no_assignee():
    return issue_query("project = MI AND resolution = Unresolved AND priority = Critical AND status != WaitingForCustomer AND assignee = unassigned")

def customer_issues():
    return issue_query("project = MI AND resolution = Unresolved AND status != WaitingForCustomer AND issuetype=Bug AND labels in (customer)")

def total_issues():
    return issue_query("project = MI AND resolution = Unresolved AND issuetype=Bug")

def sprint_info():
    params = {'state': 'active', 'maxResults': 100,
              'fields': 'key, summary, customfield_10004, resolution'}
    data = requests.get("%s/rest/agile/1.0/board/%d/sprint" % (JIRA_URI, JIRA_SPRINT_RAPID_VIEW),
                        params=params, auth=(JIRA_USER, JIRA_PASSWORD))
    data.raise_for_status()
    sprint_json = data.json()['values'][0]
    sprint_id = sprint_json['id']
    data = requests.get("%srest/agile/1.0/board/%d/sprint/%d/issue" % (JIRA_URI, JIRA_SPRINT_RAPID_VIEW, sprint_id),
                        params=params, auth=(JIRA_USER, JIRA_PASSWORD))
    data.raise_for_status()

    issue_json = data.json()
    total = sum([i['fields']['customfield_10004']
                 for i in issue_json['issues']
                 if i['fields']['customfield_10004'] is not None])
    done = sum([i['fields']['customfield_10004']
                for i in issue_json['issues']
                if i['fields']['resolution'] is not None
                and i['fields']['customfield_10004'] is not None])

    start = dateutil.parser.parse(sprint_json['startDate'])
    end = dateutil.parser.parse(sprint_json['endDate'])
    total_time = end - start
    spent_time = datetime.datetime.now(pytz.UTC) - start
    percent_time = (spent_time.total_seconds()/total_time.total_seconds())
    one_day = datetime.timedelta(days=1).total_seconds()
    timeleft = (end - datetime.datetime.now(pytz.UTC)).total_seconds()
    return {'name': sprint_json['name'],
            'start': sprint_json['startDate'],
            'end': sprint_json['endDate'],
            'timeleft': timeleft,
            'done': done,
            'todo': total-done,
            'url': "%ssecure/RapidBoard.jspa?rapidView=%d&projectKey=MI" % (JIRA_URI, JIRA_SPRINT_RAPID_VIEW)}

ONE_MINUTE=60
ONE_HOUR=ONE_MINUTE*60
ONE_DAY=ONE_HOUR*24

def nearest_time_unit_str(seconds):
    if seconds < ONE_MINUTE:
        if seconds == 1:
            return "1 second"
        else:
            return "%d seconds" % (seconds)
    elif seconds < ONE_HOUR:
        minutes = int(seconds / ONE_MINUTE)
        if minutes == 1:
            return "%d minute" % (minutes)
        else:
            return "%d minutes" % (minutes)
    elif seconds < ONE_DAY:
        hours = int(seconds / ONE_HOUR)
        minutes = seconds - (hours * ONE_HOUR)
        if hours == 1 and minutes > 5 * ONE_MINUTE:
            return "%d hour, %s" % (hours, nearest_time_unit_str(minutes))
        elif hours < 6 and minutes > 5 * ONE_MINUTE:
            return "%d hours, %s" % (hours, nearest_time_unit_str(minutes))
        else:
            return "%d hours" % (hours)
    else:
        days = int(seconds / ONE_DAY)
        hours = seconds - (days * ONE_DAY)
        if days == 1 and hours > 2 * ONE_HOUR:
            return "%d day, %s" % (days, nearest_time_unit_str(hours))
        elif days < 6 and hours > 2 * ONE_HOUR:
            return "%d days, %s" % (days, nearest_time_unit_str(hours))
        else:
            return "%d days" % (days)


warnings = []
body = []

sprint = sprint_info()
body.append("= SPRINT =")
body.append("")
body.append("- %s (%s)" % (sprint['name'], sprint['url']))
body.append("- %d points complete" % sprint['done'])
body.append("- %d points remaining" % sprint['todo'])
body.append("- %s left" % nearest_time_unit_str(sprint['timeleft']))
body.append("")

body += ["= BUGS =", ""]
critical = critical_issues()
body.append("- %d critical issue%s" % (
    len(critical), "" if len(critical) == 1 else "s"))
for i in critical:
    body.append("  * %s %s" % (i['key'], i['summary']))
    body.append("    assigned to %s" % (i['assignee'] if i['assignee'] else "NOONE!"))
    body.append("    %s" % i['url'])
    body.append("")

noassignee = critical_issues_no_assignee()
if len(noassignee) > 0:
    warnings.append("- %d critical issue%s without assignee (%s)" % (
        len(noassignee), "" if len(noassignee) == 1 else "s",
        ",".join([i['key'] for i in noassignee])))
    warnings.append("")

customer = customer_issues()
body.append("- %d customer issue%s" % (
    len(customer), "" if len(customer) == 1 else "s"))
for i in customer:
    assignee = "(%s)" % (i['assignee']) if i['assignee'] else ""
    body.append("  * %s %s %s" % (i['key'], i['summary'], assignee))
body.append("")

if len(customer) > 10:
    warnings.append("- More than 10 customer issues. There are %d." % (len(customer)))
    warnings.append("")

total = total_issues()
body.append("- %d issue%s in total" % (
    len(total), "" if len(total) == 1 else "s"))
if len(total) > 40:
    warnings.append("- More than 40 issues. There are %d." % (len(total)))
    warnings.append("")
body.append("")

body += ["= BUILDS =", ""]
for release in ['master', 'v5.4', 'v5.2', 'v5.0', "v1.9"]:
    status = get_build_status_j1(release) \
             if release == "v1.9" else get_build_status(release)

    since = datetime.datetime.now() - datetime.datetime.utcfromtimestamp(status['started']/1000)
    body.append("- %s: %s " % (release, status['result']))
    body.append("  %s" % (status['url']))
    body.append("  Last build occurred %s ago" % (nearest_time_unit_str(since.total_seconds())))
    body.append("  Took %s" % (nearest_time_unit_str(status['duration']/1000)))
    body.append("")

    if status['result'] != "SUCCESS":
        warnings.append("- %s build result was %s" % (release, status['result']))
        warnings.append("  %s" % (status['url']))
        warnings.append("")
    if since.total_seconds() > ONE_DAY*3:
        warnings.append("- Last %s build more than 3 days ago" % (release))
        warnings.append("")

if len(warnings) > 0:
    warnings = ["= NEEDS ATTENTION = ", ""] + warnings

headers = ["From: %s" % EMAIL_FROM,
           "To: %s" % EMAIL_TO,
           "Reply-To: %s" % EMAIL_FROM,
           "Subject: %s Status for %s" % ("ALL GOOD" if len(warnings) == 0
                                          else "ACTION REQUIRED",
                                          datetime.date.today().strftime("%A %d %B %Y")),
           ""]

footers = ["Status email generated by", "https://github.com/midokura/core-status-email."]

full = headers + warnings + body + footers

server = smtplib.SMTP('smtp.gmail.com:587')
server.ehlo()
server.starttls()
server.login(EMAIL_USER, EMAIL_PASS) # app generated password
server.sendmail(EMAIL_FROM, EMAIL_TO, "\n".join(full))
server.quit()


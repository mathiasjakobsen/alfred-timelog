#!/usr/bin/python
# encoding: utf-8

import sys
import collections
import xml.etree.ElementTree as ET
import argparse
import datetime
import uuid

from workflow import Workflow3, web, PasswordNotFound
from workflow.notify import notify

HELP_URL = 'https://github.com/mathiasjakobsen/alfred-timelog/issues'


Token = collections.namedtuple('Token', ['hash', 'expires', 'initials'])
Task = collections.namedtuple('Task', ['id', 'name', 'project'])
User = collections.namedtuple('User', ['password', 'username', 'token'])

def login(query):
    args = query.split(' ')
    username = args[0]
    password = args[1]

    token = fetch_token(username, password)

    if not token:
        notify(u'(╯°□°）╯︵ ', 'Invalid credentials!', 'Basso')
        return 1

    wf.save_password('password', password)
    wf.settings['username'] = username
    notify('You are ready to go!', 'Tracking time for ' + username)

def get_user():
    try:
        username = wf.settings['username']
        password = wf.get_password('password')

        def fetcher():
            return fetch_token(username, password)

        token = wf.cached_data('token', fetcher, max_age=3600)

        return User(username = username, password = password, token = token)

    except (PasswordNotFound, KeyError):
        return None

def action(args):

    action = args.split(', ')
    intent = action[0]
    identifier = action[1]


    if intent == 'select':
        task_selected(identifier)

    if intent == 'stop':
        active_task = get_active_task()
        end_registration(active_task)

def task_selected(identifier):
    active_task = get_active_task()

    if active_task:
        end_registration(active_task)

    begin_registration(identifier)

def begin_registration(identifier):
    notify(u'Yippie ki yay, motherfucker (⌐■_■)', 'Now, start being awesome.', 'Pop')
    set_active_task(identifier)

def end_registration(active_task):
    notify('Ended registration', active_task['id'], 'Pop')
    wf.store_data('active_task', None)
    insert_work(active_task['id'], active_task['datetime'], datetime.datetime.now())

def get_active_task():
    return wf.stored_data('active_task')

def set_active_task(identifier):
    wf.store_data('active_task', {
        'id': identifier,
        'datetime': datetime.datetime.now()
    })

def idle():
    active_task = get_active_task()

    if not active_task:
        wf.add_item(
            title = 'If you snooze, you loose (ง •̀_•́)ง',
            subtitle = 'Start typing to find a task, and get started!',
            valid = False
        )
    else:
        tasks = get_tasks()
        task = (item for item in tasks if item.id == active_task['id']).next()

        now = datetime.datetime.now()
        hours, minutes = hours_and_minutes(active_task['datetime'], now)

        wf.add_item(
            title = task.name,
            subtitle = 'Started tracking ' + str(hours) + ' hours and ' + str(minutes) + ' minutes ago. Hit enter to stop.',
            arg = ', '.join(['stop', task.id]),
            valid = True
        )

    wf.send_feedback()

def hours_and_minutes(then, now):
    hours = 0
    minutes = int((now - then).total_seconds() / 60.0)
    while minutes >= 60:
        hours += 1
        minutes -= 60

    return hours, minutes


def get_tasks():
    return wf.cached_data('tasks', fetch_tasks, max_age=3600)

def search(query):
    filtr = lambda t : '{} {}'.format(wf.fold_to_ascii(t.name), wf.fold_to_ascii(t.project))
    items = wf.filter(wf.fold_to_ascii(query), get_tasks(), filtr)

    if not items:
        wf.add_item(u'No matches (╯°□°）╯︵ ┻━┻', 'Try changing your search query..')

    for item in items:
        wf.add_item(title = item.name,
                    subtitle = item.project,
                    arg = ', '.join(['select', item.id]),
                    autocomplete=item.name,
                    valid=True)

    wf.send_feedback()



def insert_work(task_id, then, now):
    now = now
    user = get_user()
    hours, minutes = hours_and_minutes(then, now)
    duration = 'PT' + str(hours) + 'H' + str(minutes) + 'M'
    data = '''
        <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
            <s:Body>
                <InsertWork xmlns="http://www.timelog.com/api/tlp/v1_6">
                    <work xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
                        <WorkUnit>
                            <GUID>{guid}</GUID>
                            <AllocationGUID>{aguid}</AllocationGUID>
                            <TaskID>{task_id}</TaskID>
                            <EmployeeInitials>{initials}</EmployeeInitials>
                            <Duration>{duration}</Duration>
                            <StartDateTime>{then}</StartDateTime>
                            <EndDateTime>{now}</EndDateTime>
                            <Description>{description}</Description>
                            <TimeStamp i:nil="true" />
                            <IsEditable>false</IsEditable>
                            <AdditionalText i:nil="true" />
                            <Details i:nil="true" />
                        </WorkUnit>
                    </work>
                    <source>50</source>
                    <token xmlns:d4p1="http://www.timelog.com/api/tlp/v1_3" xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
                        <d4p1:Initials>{initials}</d4p1:Initials>
                        <d4p1:Expires>{expires}</d4p1:Expires>
                        <d4p1:Hash>{hash}</d4p1:Hash>
                    </token>
                </InsertWork>
            </s:Body>
        </s:Envelope>'''.format(
            guid = uuid.uuid4(),
            aguid = '00000000-0000-0000-0000-000000000000',
            task_id = task_id,
            initials = user.token.initials,
            duration = duration,
            then = then.isoformat(),
            now = now.isoformat(),
            description = 'I did some work. Ugh.',
            expires = user.token.expires,
            hash = user.token.hash
        )

    headers = { 'Content-Type': 'text/xml', 'SOAPAction': 'InsertWorkRequest' }
    response = web.post("https://app1.timelog.com/arnsbomedia/WebServices/ProjectManagement/V1_6/ProjectManagementServiceSecure.svc", data=data, headers=headers)
    if response.status_code == 200:
        notify(u'Done! ʕっ•ᴥ•ʔっ', 'Registed ' + str(hours) + ' hours & ' + str(minutes) + ' minutes', 'Pop')
    else:
        notify('Ohhh no', 'TimeLog responded with ' + str(response.status_code), 'Basso')


def fetch_token(username, password):
    headers = { 'Content-Type': 'text/xml', 'SOAPAction': 'GetTokenRequest' }
    data = '''
        <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>
            <GetToken xmlns="http://www.timelog.com/api/tlp/v1_2"><user>{user}</user><password>{password}</password></GetToken>
        </s:Body></s:Envelope>'''.format(password=password, user=username)


    xml = web.post("https://app1.timelog.com/arnsbomedia/WebServices/Security/V1_2/SecurityServiceSecure.svc", data=data, headers=headers).text

    ns = {
        's': 'http://schemas.xmlsoap.org/soap/envelope/',
        'a': 'http://www.timelog.com/api/tlp/v1_1',
        'i': 'http://www.w3.org/2001/XMLSchema-instance'
    }

    root = ET.fromstring(str(xml))
    path = 's:Body/{http://www.timelog.com/api/tlp/v1_2}GetTokenResponse/'
    path += '{http://www.timelog.com/api/tlp/v1_2}GetTokenResult/'
    path += '{http://www.timelog.com/api/tlp/v1_1}Return/'
    path += '{http://www.timelog.com/api/tlp/v1_2}SecurityToken/'

    token = root.findall(path, ns)

    try:
        return Token(hash=token[2].text, expires=token[1].text, initials=token[0].text)
    except IndexError:
        return None

def fetch_tasks():
    user = get_user()
    data = '''
        <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
            <s:Body>
                <GetTasksAllocatedToEmployee xmlns="http://www.timelog.com/api/tlp/v1_6">
                    <initials>{initials}</initials>
                    <token xmlns:d4p1="http://www.timelog.com/api/tlp/v1_3" xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
                        <d4p1:Initials>{initials}</d4p1:Initials>
                        <d4p1:Expires>{expires}</d4p1:Expires>
                        <d4p1:Hash>{hash}</d4p1:Hash>
                    </token>
                </GetTasksAllocatedToEmployee>
            </s:Body>
        </s:Envelope>
    '''.format(initials=user.token.initials, expires=user.token.expires, hash=user.token.hash)

    headers = { 'Content-Type': 'text/xml', 'SOAPAction': 'GetTasksAllocatedToEmployeeRequest' }
    xml = web.post("https://app1.timelog.com/arnsbomedia/WebServices/ProjectManagement/V1_6/ProjectManagementServiceSecure.svc", data=data, headers=headers).text
    foo = xml.encode('utf-8')

    ns = {
        's': 'http://schemas.xmlsoap.org/soap/envelope/',
        'a': 'http://www.timelog.com/api/tlp/v1_1',
        'i': 'http://www.w3.org/2001/XMLSchema-instance'
    }

    root = ET.fromstring(foo)
    path = 's:Body/{http://www.timelog.com/api/tlp/v1_6}GetTasksAllocatedToEmployeeResponse/'
    path += '{http://www.timelog.com/api/tlp/v1_6}GetTasksAllocatedToEmployeeResult/'
    path += '{http://api.timelog.com}Return/'
    path += '{http://www.timelog.com/api/tlp/v1_6}Task'

    tasks = []

    for elm in root.findall(path, ns):
        uuid = elm.find('{http://www.timelog.com/api/tlp/v1_6}TaskID', ns).text
        name = elm.find('{http://www.timelog.com/api/tlp/v1_6}Name', ns).text
        project = elm.find('{http://www.timelog.com/api/tlp/v1_6}Details/{http://www.timelog.com/api/tlp/v1_6}ProjectHeader/{http://www.timelog.com/api/tlp/v1_6}Name', ns).text
        task = Task(id=uuid, name=name, project=project)
        tasks.append(task)

    return tasks

def main(wf):
    parser = argparse.ArgumentParser()
    parser.add_argument('query', nargs='?', default=None)
    parser.add_argument('--login', dest='login', nargs='?', default=None)
    parser.add_argument('--action', dest='action', nargs='?', default=None)

    args = parser.parse_args(wf.args)

    if args.login:
        return login(args.login)

    if not get_user():
        wf.add_item(title="Not logged in! Please run 'timelog login'", valid=False)
        wf.send_feedback()
        return 1

    if args.action:
        return action(args.action)

    if len(args.query):
        return search(args.query)

    return idle()

if __name__ == '__main__':
    wf = Workflow3(help_url=HELP_URL)
    sys.exit(wf.run(main))

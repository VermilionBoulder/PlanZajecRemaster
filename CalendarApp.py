from __future__ import print_function

import datetime
import os.path
import re
import ssl
import sys
from itertools import zip_longest

import bs4
import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from requests import adapters

import Event

PLAN_URL = "https://planzajec.uek.krakow.pl/index.php?typ=G&id=186581&okres=1"

DEFAULT_SCOPES = ['https://www.googleapis.com/auth/calendar']
DEFAULT_CALENDAR_ID = 'b5d70ec1afdce64dc795396461dafe97bb82e3ab3f0f6933e3404830d9660714@group.calendar.google.com'
DEFAULT_TIME_OFFSET = datetime.timedelta(days=14)

url_without_set_time_period = '&'.join(PLAN_URL.split('&')[:-1])
TWO_WEEKS_URL = f"{url_without_set_time_period}&okres=1"
SEMESTER_URL = f"{url_without_set_time_period}&okres=2"


class CalendarApp:
    def __init__(self, calendar_id=DEFAULT_CALENDAR_ID, time_offset=DEFAULT_TIME_OFFSET):
        self.scopes = DEFAULT_SCOPES
        self.calendar_id = calendar_id
        self.time_offset = time_offset

        self.creds = self._get_credentials()
        self.service = self._get_service()  # TODO fix this

    def main(self, args):
        if isinstance(args, list) and len(args) >= 2:
            match args[1]:
                case "two_weeks" | "Two_weeks":
                    self.update_calendar(TWO_WEEKS_URL)
                case _:
                    self.update_calendar(SEMESTER_URL)
        else:
            print(f"Bad argument(s): {args[1:]}\n"
                  f"Updating entire calendar")
            self.update_calendar(SEMESTER_URL)

    def update_calendar(self, plan_url):
        events_in_website_plan = self._get_events_from_website_plan(plan_url)
        if plan_url == TWO_WEEKS_URL:
            events_in_google_calendar = self._get_events_from_google_calendar(time_bounds=self._get_time_bounds())
        elif plan_url == SEMESTER_URL:
            events_in_google_calendar = self._get_events_from_google_calendar()
        else:
            raise ValueError("Bad URL provided - neither TWO_WEEKS_URL nor SEMESTER!")

        for event in zip_longest(events_in_website_plan,
                                 events_in_google_calendar,
                                 fillvalue=None):
            # TODO:
            #  If event in calendar but not on website: delete
            #  If event in calendar and on website: skip
            #  If event not in calendar but on website: add
            #  Compare events based on summary and time
            print(event[0].get('summary'), event[1].get('summary'))

    def _get_events_from_google_calendar(self, time_bounds=()):
        if len(time_bounds) == 2:
            time_min, time_max = time_bounds
            print(f'Getting events for deletion between {time_min} and {time_max}')
            events_result = self.service.events().list(calendarId=self.calendar_id,
                                                       singleEvents=True, timeMin=time_min,
                                                       timeMax=time_max, orderBy='startTime').execute()
        else:
            print('Getting events for deletion')
            events_result = self.service.events().list(calendarId=self.calendar_id,
                                                       singleEvents=True, orderBy='startTime').execute()
        events = events_result.get('items', [])
        print(f"Events in Google Calendar: {len(events)}")
        return events

    def _get_credentials(self):
        creds = None
        if os.path.exists('token.json'):
            creds = Credentials.from_authorized_user_file('token.json', self.scopes)
            # If there are no (valid) credentials available, let the user log in.
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file('credentials.json', self.scopes)
                creds = flow.run_local_server(port=0)
            # Save the credentials for the next run
            with open('token.json', 'w') as token:
                token.write(creds.to_json())
        return creds

    def _get_service(self):
        try:
            service = build('calendar', 'v3', credentials=self.creds)
            return service
        except HttpError as error:
            print(f'Connection error occurred: {error}')
            raise

    def _insert_events(self, events=()):
        for event in events:
            self.service.events().insert(calendarId=self.calendar_id, body=event).execute()
            print(f"Event created: {event.get('summary')}")

    def _get_events_from_website_plan(self, plan_url):
        """
        Gets events from planzajec.uek.krakow.pl
        :param plan_url: Url of plan to get events from
        :return: List of events
        """
        class TLSAdapter(requests.adapters.HTTPAdapter):
            def init_poolmanager(self, *args, **kwargs):
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.set_ciphers('DEFAULT@SECLEVEL=1')
                kwargs['ssl_context'] = ctx
                return super(TLSAdapter, self).init_poolmanager(*args, **kwargs)

        session = requests.session()
        session.mount('https://', TLSAdapter())

        try:
            r = session.get(plan_url, verify=False,
                            proxies={"http": "http://lab-proxy.krk-lab.nsn-rdnet.net:8080",
                                     "https": "http://lab-proxy.krk-lab.nsn-rdnet.net:8080"})
        except Exception as exception:
            print(f"Encountered exception: {exception}\n"
                  f"Trying to request resource without proxy...")
            r = session.get(plan_url, verify=False)

        soup = bs4.BeautifulSoup(r.content, 'html.parser')
        table = soup.find('table')

        headers = [header.text for header in table.find_all('th')]
        results = [{headers[i]: cell for i, cell in enumerate(row.find_all('td'))}
                   for row in table.find_all('tr')]

        events = []
        for event in [result for result in results if len(result) == 6]:  # Skip invalid events and transfers
            start, end = re.findall(r"\d\d:\d\d", event.get('Dzień, godzina').text)
            start_formatted = datetime.datetime.strptime(f"{event.get('Termin').text} {start}", "%Y-%m-%d %H:%M")
            end_formatted = datetime.datetime.strptime(f"{event.get('Termin').text} {end}", "%Y-%m-%d %H:%M")
            event_type = event.get('Typ').text.lower()
            if "ćwiczenia" in event_type:
                event_type_short = "Ćw"
            elif "wykład" in event_type:
                event_type_short = "Wk"
            elif "lektorat" in event_type:
                event_type_short = "Lk"
            elif "przeniesienie" in event_type:
                event_type_short = "Przeniesione:"
            else:
                event_type_short = ""
            summary = f"{event_type_short}{' ' if event_type_short else ''}{event.get('Przedmiot').text}"
            link = ""
            if event.get('Sala').contents:
                if isinstance(link_container := event.get('Sala').contents[0], bs4.element.Tag):
                    link = link_container.attrs['href']
            description = f"Prowadzący: {event.get('Nauczyciel').text}\n" \
                          f"{event.get('Sala').text.title()}{': ' + link if link else ''}"
            events.append(Event.Event(start_formatted, end_formatted, summary, description).get_calendar_event())
        return events

    def _delete_events(self, bounds=()):
        if len(bounds) == 2:
            time_min, time_max = bounds
            print(f'Getting events for deletion between {time_min} and {time_max}')
            events_result = self.service.events().list(calendarId=self.calendar_id,
                                                       singleEvents=True, timeMin=time_min,
                                                       timeMax=time_max, orderBy='startTime').execute()
        else:
            print('Getting events for deletion')
            events_result = self.service.events().list(calendarId=self.calendar_id,
                                                       singleEvents=True, orderBy='startTime').execute()
        events = events_result.get('items', [])
        if events:
            print(f"Events found: {len(events)}")
            for event in events:
                start = event.get('start').get('dateTime', event.get('start').get('date'))
                event_id = event.get('id')
                print(f"Deleting: {start} {event.get('summary')}...")
                self.service.events().delete(calendarId=self.calendar_id, eventId=event_id).execute()
        else:
            print("No events found.")

    def _get_time_bounds(self):
        """
        Defines datetime objects for now and now + DEFAULT_TIME_OFFSET
        :return: now, now_plus_time_offset
        """
        now = datetime.datetime.today()
        now = now.replace(hour=0, minute=0, second=0, microsecond=0)
        now_plus_time_offset = now + DEFAULT_TIME_OFFSET
        now = now.isoformat() + 'Z'
        now_plus_time_offset = now_plus_time_offset.isoformat() + 'Z'
        return now, now_plus_time_offset


if __name__ == '__main__':
    print("Starting script")
    print(f"Executable: {sys.executable}\n"
          f"Working dir: {os.getcwd()}")
    app = CalendarApp()
    app.main(sys.argv)

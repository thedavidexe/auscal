import os
import json
from time import sleep
import datetime
import os.path
import retry

import openai
import tiktoken
# enc = tiktoken.encoding_for_model("gpt4")

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
from webdriver_manager.chrome import ChromeDriverManager

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from cal_id import CALENDAR_ID

GPT_PROMPT = "Without including any explanations in your responses please parse the following webpage data and extract information about all of the events into a json data structure. The top level of the structure is a list and the keys of each event are Title, Date, and Description. The format of the date is MM-DD."

@retry.retry(openai.error.ServiceUnavailableError, tries=3, delay=10)
def gpt_request(webpage_contents):
    print("sending web contents to gpt")
    return openai.ChatCompletion.create(
    model="gpt-3.5-turbo",
    messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": GPT_PROMPT + "\n\n" + webpage_contents},
        ]
    )

@retry.retry(json.JSONDecodeError, tries=3, delay=1)
def webpage_to_json(webpage_text):
        response = gpt_request(webpage_text)
        return json.loads(response["choices"][0]["message"]["content"])
        
def main():
    openai.api_key = os.getenv("OPENAI_API_KEY")
    # print(openai.api_key)

    # print(openai.Model.list())
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    driver=webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    urls = ["https://512beach.com/events",
            "https://www.aussiesaustin.com/Events.aspx",
            "https://citylimitsports.com/tournaments.php",
            "https://512beach.com/leagues"]
    for url in urls:
        driver.get(url)
        wait = WebDriverWait(driver, 10)
        wait.until(EC.url_to_be(url))
        print(f"waiting for {url} webpage to load")


        sleep(5)  # TODO: dynamically wait until we see correct web elements loaded in, for now 5s works
        soup = BeautifulSoup(driver.page_source, "lxml")
        webpage_text = soup.get_text()
        print(webpage_text)

        event_data = webpage_to_json(webpage_text)
            
        print(json.dumps(event_data, indent=1))
        creds = Credentials.from_authorized_user_file('token.json')
        try:
            service = build('calendar', 'v3', credentials=creds)
            # First get events from calendar so we can make sure not to add duplicates
            events_already_in_calendar = []
            now = datetime.datetime.now()
            past = now - datetime.timedelta(days=200)
            start_from_time = past.isoformat() + 'Z'
            event_result = service.events().list(calendarId=CALENDAR_ID, timeMin=start_from_time,
                                                maxResults=1000, singleEvents=True,
                                                orderBy='startTime').execute()
            events_already_in_calendar = event_result.get('items', [])
            print("dexe all events already in calendar:")
            print(events_already_in_calendar)
            current_year = datetime.datetime.now().year
            for event in event_data:
                cal_event = {
                    "summary": event["Title"],
                    "description": event["Description"] + "\n\n" + url,
                    "start": {
                        "date": f"{current_year}-{event['Date']}"
                    },
                    "end": {
                        "date": f"{current_year}-{event['Date']}"
                    }
                }
                print(cal_event)
                for scheduled_event in events_already_in_calendar:
                    if scheduled_event.get("summary") == cal_event["summary"] and \
                        scheduled_event.get("start").get("date") == cal_event["start"]["date"]:
                        print("Event already in calendar, skipping")
                        break
                else:
                    service.events().insert(calendarId=CALENDAR_ID, body=cal_event).execute()
        except HttpError as error:
            print('An error occurred: %s' % error)

if __name__ == '__main__':
    main()

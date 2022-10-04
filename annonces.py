#!/usr/bin/env python3
import logging
from pathlib import Path
import time
logging.basicConfig(
    level="INFO",
    format="%(asctime)s - %(name)s - [ %(message)s ]",
    datefmt='%d-%b-%y %H:%M:%S',
    force=True,
    handlers=[
        logging.FileHandler(Path(__file__).with_name('logs.log')),
        logging.StreamHandler()
    ])

import requests
import json
import urllib
from tinydb import TinyDB, where
from mailjet_rest import Client
import asyncio
from pyppeteer import launch

logging.info('starting process')

categories_to_remove = {
    "automobiles.nc": ["Divers", "Pièces moteurs", "Carrosseries", "Éclairages"],
    "2roues.nc": ["Pièces détachées Moto"]
}    

current_hit = 0
current_search = 0
current_email_to = 0


p = Path(__file__).with_name('config.json')
with p.open('r') as f:
  config = json.load(f)

p = Path(__file__).with_name('mail-config.json')
with p.open('r') as f:
  mail_config = json.load(f)

def filter_hit():
    if current_hit['kind'] != "sell" or  current_hit['category']['root_name'] != current_search['site'] or current_hit['category']['name'] in categories_to_remove[current_search['site']]:
        return False
    if current_search.get('max_km') and current_hit['custom_fields'].get('km') and current_hit['custom_fields']['km'] > current_search['max_km']:
        #the hit as too much mileage
        return False
    return True

async def send_email():
    api_key = mail_config['MailJet']['Api_Key']
    api_secret = mail_config['MailJet']['Api_Secret']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')
    base64Attachment = await screenshot()
    data = {
    'Messages': [
        {
        "From": mail_config['MailJet']['From'],
        "To": [
            {
            "Email": current_email_to
            }
        ],
        "Subject": "New add on annonces.nc for your search " + current_search['keywords'],
        "HTMLPart": "<a href=\"https://annonces.nc/" + current_search['site'][:-3]+"/posts/" + current_hit['slug']+"\">" + current_hit['title'] + "</a></li>",
        "Attachments": [
            {
                    "ContentType": "image/png",
                    "Filename": "screenshot.png",
                    "Base64Content": base64Attachment
            }
            ]
        }
    ]
    }
    result = mailjet.send.create(data=data)

async def process_new_hit():
    processedAdsTable.insert({'search_id': current_search['id'] , 'hit_id': current_hit['id']})
    if filter_hit() == True:        
        print('NEW AD! '  + str(current_search['id']) + ' ' + str(current_hit['id']) + ' - ' + str(current_hit['title']))
        print('**************')
        await send_email()


async def process_hit():
    query = processedAdsTable.get((where('hit_id') == current_hit['id']) & (where('search_id') == current_search['id']))
    if query is None:
        await process_new_hit()        
    else:
        print('skipping ad ' + str(current_hit['id']) + ' - ' + str(current_hit['title']))

async def screenshot():
    browser = await launch()
    page = await browser.newPage()
    await page.goto("https://annonces.nc/" + current_search['site'][:-3] + "/posts/"+current_hit['slug'])
    element = await page.querySelector('#cookie-policy-container > div:nth-child(2) > div > button')
    await element.click()
    hit_element = await page.querySelector('annonces-post-detail > div')
    result = await hit_element.screenshot(encoding = "base64")
    await browser.close()
    return result

db = TinyDB(Path(__file__).with_name('db.json'))
processedAdsTable = db.table('processed') 

url = {
    "x-algolia-agent": "Algolia for JavaScript (3.35.1); Browser",
    "x-algolia-application-id": "GVLE5Z29MR",
    "x-algolia-api-key": "fa6c9390760eb58e3197d2689a2a16f9"
}

async def process():
    for x in config:
        global current_email_to
        current_email_to = x['email']
        for search in x['searches']:
            global current_search   
            current_search = search
            page = 0
            while (True):
                params = {
                    "query": search['keywords'],
                    "page": page
                }
                data = {"params" : urllib.parse.urlencode(params)}
                response = requests.post('https://gvle5z29mr-dsn.algolia.net/1/indexes/Post/query?' + urllib.parse.urlencode(url), data = json.dumps(data), verify = False)
                results = response.json()
                if len(results['hits']) == 0:
                    break
                for hit in results['hits']:
                    global current_hit   
                    current_hit = hit
                    await process_hit()
                page = page + 1

asyncio.run(process())

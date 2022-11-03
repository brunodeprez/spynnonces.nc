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

import smtplib
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email import encoders
import os

logging.info('starting process')

categories_to_remove = {
    "automobiles.nc": ["Divers", "Pièces moteurs", "Carrosseries", "Éclairages"],
    "2roues.nc": ["Pièces détachées Moto"],
    "annonces.nc": []
}

global current_hit
global current_search
global current_email_to
global browser
global current_config

p = Path(__file__).with_name('config.json')
with p.open('r') as f:
  config = json.load(f)

p = Path(__file__).with_name('mail-config.json')
with p.open('r') as f:
  mail_config = json.load(f)

p = Path(__file__).with_name('smtp-config.json')
with p.open('r') as f:
  smtp_config = json.load(f)


def filter_hit():
    if current_hit['kind'] != "sell" or  current_hit['category']['root_name'] != current_search['site'] or current_hit['category']['name'] in categories_to_remove[current_search['site']]:
        return False
    if current_search.get('max_km') and current_hit['custom_fields'].get('km') and current_hit['custom_fields']['km'] > current_search['max_km']:
        #the hit as too much mileage
        return False
    return True


def send_email_SMTP(smtpHost, smtpPort, mailUname, mailPwd, fromEmail, mailSubject, mailContentHtml, recepientsMailList, attachmentFile):
    # create message object
    msg = MIMEMultipart()
    msg['From'] = fromEmail
    msg['To'] = ','.join(recepientsMailList)
    msg['Subject'] = mailSubject
    # msg.attach(MIMEText(mailContentText, 'plain'))
    msg.attach(MIMEText(mailContentHtml, 'html'))

    #---- ATTACHMENT PART ---------------
    # open the file to be sent 
    # This is the binary part(The Attachment):
    part = MIMEBase('image','png')
    part.set_payload(attachmentFile)
    part.add_header('Content-Transfer-Encoding', 'base64')
    part['Content-Disposition'] = 'attachment; filename="screenshot.png"'
    msg.attach(part)    #--------------------------------------
    
     # Send message object as email using smptplib
    s = smtplib.SMTP(smtpHost, smtpPort)
    s.starttls()
    s.login(mailUname, mailPwd)
    msgText = msg.as_string()
    sendErrs = s.sendmail(fromEmail, [recepientsMailList], msgText)
    s.quit()

    # check if errors occured and handle them accordingly
    if not len(sendErrs.keys()) == 0:
        raise Exception("Errors occurred while sending email", sendErrs)

async def send_email_API(status):
    api_key = mail_config['MailJet']['Api_Key']
    api_secret = mail_config['MailJet']['Api_Secret']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')
    base64Attachment = await screenshot() if current_config['screenshot'] ==  1 else None
    data = {
        "Messages": [
            {
            "From": mail_config['MailJet']['From'],
            "To": [
                {
                "Email": current_config['email']
                }
            ],
            "Subject": "New "+ "-".join(status) +" on annonces.nc for your search " + current_search['keywords'],
            "HTMLPart": "<a href=\"https://annonces.nc/" + current_search['site'][:-3]+"/posts/" + current_hit['slug']+"\">" + current_hit['title'] + "</a></li>",
            }
        ]
    }
    if base64Attachment is not None:
        data['Messages'][0]['Attachments'] = [
            {
                    "ContentType": "image/png",
                    "Filename": "screenshot.png",
                    "Base64Content": base64Attachment
            }
        ]      

    result = mailjet.send.create(data=data)

async def send_email(status):
    # mail body, recepients, attachment files
    mailSubject = "New "+ "-".join(status) +" on annonces.nc for your search " + current_search['keywords']
    mailContentHtml = "<a href=\"https://annonces.nc/" + current_search['site'][:-3]+"/posts/" + current_hit['slug']+"\">" + current_hit['title'] + "</a></li>"
    
    # generating the attachment picture
    Attachment = await screenshot()

    send_email_SMTP(smtp_config['smtpHost'], smtp_config['smtpPort'], smtp_config['mailUname'], smtp_config['mailPwd'], smtp_config['fromEmail'], 
            mailSubject, mailContentHtml, current_config['email'], Attachment)

    print("Email sent...")

# async def process_new_hit():
#     processedAdsTable.insert({'search_id': current_search['id'] , 'hit_id': current_hit['id']})
#     if filter_hit() == True:
#         print('NEW AD! '  + str(current_search['id']) + ' ' + str(current_hit['id']) + ' - ' + str(current_hit['title']))
#         await send_email()

# async def process_hit():
#     status = get_hit_status()
#     query = processedAdsTable.get((where('hit_id') == current_hit['id']) & (where('search_id') == current_search['id']))
#     if query is None:
#         await process_new_hit()
#     else:
#         print('skipping ad ' + str(current_hit['id']) + ' - ' + str(current_hit['title']))

async def process_hit():
    status = []
    hit = processedAdsTable.get((where('hit_id') == current_hit['id']) & (where('search_id') == current_search['id']))
    # the hit is already in the database, no changes -> skip   
    if hit is not None and hit.get('price') == current_hit['price'] and hit.get('description') == current_hit['description'] and hit.get('title') == current_hit['title']:
        return
    # new hit
    if hit is None:
        processedAdsTable.insert({'search_id': current_search['id'], 'hit_id': current_hit['id'], 'title': current_hit['title'], 'price': current_hit['price'], 'description': current_hit['description']})
        status.append('ad')
    else:
        # new price for existing hit    
        if hit.get('price') != current_hit['price']:
            processedAdsTable.update({'price': current_hit['price']}, (where('hit_id') == current_hit['id']) & (where('search_id') == current_search['id']))
            status.append('price')
        # new title or description for existing hit
        if hit.get('description') != current_hit['description'] or hit.get('title') != current_hit['title']:
            status.append('title')
            status.append('description')
            processedAdsTable.update({'description': current_hit['description'], 'title': current_hit['title']}, (where('hit_id') == current_hit['id']) & (where('search_id') == current_search['id']))
    # compare hit to personal filters
    if filter_hit() == True:
        logging.info('New | ' + " - ".join(status) + ' | ' + current_hit['title'])
        if current_config['send_email'] == 1:
            await send_email(status)


async def screenshot():
    page = await browser.newPage()
    page.setDefaultNavigationTimeout(0)
    await page.goto("http://annonces.nc/" + current_search['site'][:-3] + "/posts/"+current_hit['slug'])
    time.sleep(3)
    element = await page.querySelector('#cookie-policy-container > div:nth-child(2) > div > button')
    if element != None:
        await element.click()
    await page.evaluate('document.querySelector("nav").remove()')
    hit_element = await page.querySelector('annonces-post-detail > div')
    if hit_element == None:
        await page.screenshot({'path': current_hit['slug']+'.png'})
    result = await hit_element.screenshot(encoding = "base64")
    await page.close()
    return result

db = TinyDB(Path(__file__).with_name('db.json'))
processedAdsTable = db.table('processed')

url = {
    "x-algolia-agent": "Algolia for JavaScript (3.35.1); Browser",
    "x-algolia-application-id": "GVLE5Z29MR",
    "x-algolia-api-key": "fa6c9390760eb58e3197d2689a2a16f9"
}

async def process():
    global browser    
    browser = await launch(ignoreHTTPSErrors = True, options = {'args': ['--no-sandbox', '--ignore-certificate-errors', '--ignore-certificate-errors-spki-list'] })
    for x in config:
        global current_config
        current_config = x
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
    await browser.close()
    logging.info('finish process')

asyncio.run(process())

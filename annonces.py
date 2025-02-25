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
import asyncio
from pyppeteer import launch
import smtplib
import sys
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.info('starting process')

categories_to_remove = {
    "automobiles.nc": ["Divers", "Pièces moteurs", "Carrosseries", "Éclairages"],
    "2roues.nc": ["Pièces détachées Moto"],
    "annonces.nc": []
}

global current_hit
global current_search
global browser
global current_config

p = Path(__file__).with_name('config.json')
with p.open('r') as f:
  config = json.load(f)

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

def send_email_SMTP(smtpHost, smtpPort, mailUname, mailPwd, fromEmail, mailSubject, mailContentHtml, recepientsMailList, attachmentFile=None):
    # create message object
    msg = MIMEMultipart()
    msg['From'] = fromEmail
    msg['To'] = ','.join(recepientsMailList) if isinstance(recepientsMailList, list) else recepientsMailList
    msg['Subject'] = mailSubject
    msg.attach(MIMEText(mailContentHtml, 'html'))

    if attachmentFile:
        #---- ATTACHMENT PART ---------------
        part = MIMEBase('image','png')
        part.set_payload(attachmentFile)
        part.add_header('Content-Transfer-Encoding', 'base64')
        part['Content-Disposition'] = 'attachment; filename="screenshot.png"'
        msg.attach(part)    
    
    # Send message object as email using smptplib
    s = smtplib.SMTP(smtpHost, smtpPort)
    s.starttls()
    s.login(mailUname, mailPwd)
    msgText = msg.as_string()
    sendErrs = s.sendmail(fromEmail, [recepientsMailList] if isinstance(recepientsMailList, list) else [recepientsMailList], msgText)
    s.quit()

    # check if errors occured and handle them accordingly
    if not len(sendErrs.keys()) == 0:
        raise Exception("Errors occurred while sending email", sendErrs)


async def send_email(status, hit_data):
    try:
        # Get the old data from hit_data parameter
        old_data = hit_data if hit_data else {}
        current_time = time.strftime("%Y-%m-%d %H:%M:%S")
        
        # Construct email subject
        mailSubject = "New "+ "-".join(status) +" on annonces.nc for your search " + current_search['keywords'].upper() + ' - ' + str(current_hit['price']) +" (CFP)"
        
        # Main item details table
        main_table = f"""
        <table style="width:100%; border-collapse:collapse; margin-bottom:20px; font-family:Arial, sans-serif; margin-left:0; margin-right:auto;">
            <tr style="background-color:#f2f2f2;">
                <th colspan="2" style="padding:12px; text-align:left; border:1px solid #ddd;">
                    <h2 style="margin:0;"><a href="https://annonces.nc/{current_search['site'][:-3]}/posts/{current_hit['slug']}" style="color:#0066cc; text-decoration:none;">{current_hit['title']}</a></h2>
                </th>
            </tr>
            <tr>
                <td style="padding:10px; border:1px solid #ddd; width:150px; font-weight:bold;">Current Price:</td>
                <td style="padding:10px; border:1px solid #ddd;"><strong>{current_hit['price']} CFP</strong></td>
            </tr>
            <tr>
                <td style="padding:10px; border:1px solid #ddd; font-weight:bold; vertical-align:top;">Description:</td>
                <td style="padding:10px; border:1px solid #ddd;">{current_hit['highlighted_description']}</td>
            </tr>
        """
        
        # Add custom fields if available
        if current_hit.get('custom_fields'):
            for field_name, field_value in current_hit['custom_fields'].items():
                if field_value and str(field_value).strip():
                    main_table += f"""
                    <tr>
                        <td style="padding:10px; border:1px solid #ddd; font-weight:bold;">{field_name.replace('_', ' ').title()}:</td>
                        <td style="padding:10px; border:1px solid #ddd;">{field_value}</td>
                    </tr>
                    """
        
        # Add first seen timestamp if new ad
        if 'ad' in status:
            main_table += f"""
            <tr>
                <td style="padding:10px; border:1px solid #ddd; font-weight:bold;">First Seen:</td>
                <td style="padding:10px; border:1px solid #ddd;">{current_time}</td>
            </tr>
            """
        
        main_table += "</table>"

        # Changes table if there are any changes
        changes_table = ""
        if 'price' in status or 'description' in status or 'title' in status:
            changes_table = """
            <h3 style="margin-top:30px; color:#444; text-align:left;">Changes Detected</h3>
            <table style="width:100%; border-collapse:collapse; margin-bottom:20px; font-family:Arial, sans-serif; margin-left:0; margin-right:auto;">
                <tr style="background-color:#f2f2f2;">
                    <th style="padding:10px; text-align:left; border:1px solid #ddd; width:15%;">Field</th>
                    <th style="padding:10px; text-align:left; border:1px solid #ddd; width:35%;">Old Value</th>
                    <th style="padding:10px; text-align:left; border:1px solid #ddd; width:15%;">Last Updated</th>
                    <th style="padding:10px; text-align:left; border:1px solid #ddd; width:35%;">New Value</th>
                </tr>
            """
            
            if 'price' in status and old_data.get('price') != current_hit['price']:
                changes_table += f"""
                <tr>
                    <td style="padding:10px; border:1px solid #ddd; font-weight:bold;">Price</td>
                    <td style="padding:10px; border:1px solid #ddd;">{old_data.get('price', 'N/A')} CFP</td>
                    <td style="padding:10px; border:1px solid #ddd; font-size:12px;">{old_data.get('price_timestamp', 'N/A')}</td>
                    <td style="padding:10px; border:1px solid #ddd;">{current_hit['price']} CFP</td>
                </tr>
                """
            
            if 'title' in status and old_data.get('title') != current_hit['title']:
                changes_table += f"""
                <tr>
                    <td style="padding:10px; border:1px solid #ddd; font-weight:bold;">Title</td>
                    <td style="padding:10px; border:1px solid #ddd;">{old_data.get('title', 'N/A')}</td>
                    <td style="padding:10px; border:1px solid #ddd; font-size:12px;">{old_data.get('title_timestamp', 'N/A')}</td>
                    <td style="padding:10px; border:1px solid #ddd;">{current_hit['title']}</td>
                </tr>
                """
                
            if 'description' in status and old_data.get('description') != current_hit['highlighted_description']:
                changes_table += f"""
                <tr>
                    <td style="padding:10px; border:1px solid #ddd; font-weight:bold; vertical-align:top;">Description</td>
                    <td style="padding:10px; border:1px solid #ddd;">{old_data.get('description', 'N/A')}</td>
                    <td style="padding:10px; border:1px solid #ddd; font-size:12px; vertical-align:top;">{old_data.get('description_timestamp', 'N/A')}</td>
                    <td style="padding:10px; border:1px solid #ddd;">{current_hit['highlighted_description']}</td>
                </tr>
                """
                
            changes_table += "</table>"
        
        # Combine the content
        mailContentHtml = f"""
        <div style="max-width:800px; margin:0; padding:20px; border:1px solid #ddd; border-radius:5px; text-align:left;">
            {main_table}
            {changes_table}
            <p style="color:#777; font-size:12px; margin-top:30px; border-top:1px solid #eee; padding-top:10px;">
                This is an automated notification from annonces.nc tracker for search: "{current_search['keywords']}".
                <br>Last checked: {current_time}
            </p>
        </div>
        """
        
        try:
            # Generate screenshot
            Attachment = await screenshot()
            
            # Send email with or without attachment
            if Attachment is None:
                logging.warning("Screenshot failed, sending email without attachment")
                send_email_SMTP(smtp_config['smtpHost'], smtp_config['smtpPort'], 
                              smtp_config['mailUname'], smtp_config['mailPwd'], 
                              smtp_config['fromEmail'], mailSubject, mailContentHtml, 
                              current_config['email'])
            else:
                send_email_SMTP(smtp_config['smtpHost'], smtp_config['smtpPort'], 
                              smtp_config['mailUname'], smtp_config['mailPwd'], 
                              smtp_config['fromEmail'], mailSubject, mailContentHtml, 
                              current_config['email'], Attachment)
                
            logging.info("Email sent with current description and change history...")
            logging.info("")

            await asyncio.sleep(1)
            
        except Exception as e:
            logging.error(f"Screenshot or email sending failed: {e}")
            # Try to send email without attachment if screenshot fails
            send_email_SMTP(smtp_config['smtpHost'], smtp_config['smtpPort'], 
                          smtp_config['mailUname'], smtp_config['mailPwd'], 
                          smtp_config['fromEmail'], mailSubject, mailContentHtml, 
                          current_config['email'])
            
    except Exception as e:
        logging.error(f"Email process failed: {e}")

        
async def process_hit():
    try:
        status = []
        hit = processedAdsTable.get((where('hit_id') == current_hit['id']) & (where('search_id') == current_search['id']))
        current_time = time.strftime("%Y-%m-%d %H:%M:%S")
        
        # Store old data before any updates
        old_data = None
        if hit is not None:
            old_data = {
                'price': hit.get('price'),
                'title': hit.get('title'),
                'description': hit.get('description'),
                'price_timestamp': hit.get('price_timestamp'),
                'title_timestamp': hit.get('title_timestamp'),
                'description_timestamp': hit.get('description_timestamp')
            }
        
        # the hit is already in the database, no changes -> skip   
        if hit is not None and hit.get('price') == current_hit['price'] and hit.get('description') == current_hit['highlighted_description'] and hit.get('title') == current_hit['title']:
            return
            
        # new hit
        if hit is None:
            processedAdsTable.insert({
                'search_id': current_search['id'], 
                'hit_id': current_hit['id'], 
                'title': current_hit['title'], 
                'price': current_hit['price'], 
                'description': current_hit['highlighted_description'],
                'first_seen': current_time,
                'price_timestamp': current_time,
                'title_timestamp': current_time,
                'description_timestamp': current_time
            })
            status.append('ad')
        else:
            updates = {}
            
            # new price for existing hit    
            if hit.get('price') != current_hit['price']:
                updates['price'] = current_hit['price']
                updates['price_timestamp'] = current_time
                status.append('price')
                
            # new title for existing hit
            if hit.get('title') != current_hit['title']:
                updates['title'] = current_hit['title']
                updates['title_timestamp'] = current_time
                status.append('title')
                
            # new description for existing hit
            if hit.get('description') != current_hit['highlighted_description']:
                updates['description'] = current_hit['highlighted_description']
                updates['description_timestamp'] = current_time
                status.append('description')
                
            # Apply all updates at once
            if updates:
                processedAdsTable.update(updates, 
                    (where('hit_id') == current_hit['id']) & (where('search_id') == current_search['id']))
                
        # compare hit to personal filters
        if filter_hit() == True:
            logging.info('New | ' + " - ".join(status) + ' | ' + current_hit['title'])
            if current_config['send_email'] == 1:
                await send_email(status, old_data)
                await asyncio.sleep(2)
                
    except Exception as e:
        logging.error(f"Error processing hit: {e}")


async def screenshot():
    try:
        page = await browser.newPage()
        page.setDefaultNavigationTimeout(0)
        await page.goto("http://annonces.nc/" + current_search['site'][:-3] + "/posts/"+current_hit['slug'])
        
        # Initial wait for page load
        await asyncio.sleep(3)
        
        # Function to handle various consent popups
        async def handle_popups():
            try:
                # Handle cookie policy popup
                cookie_button = await page.querySelector('#cookie-policy-container > div:nth-child(2) > div > button')
                if cookie_button:
                    await cookie_button.click()
                    await asyncio.sleep(1)
                
                # Get all frames
                frames = page.frames
                
                # Try to find and handle Google consent in main page first
                google_consent_selectors = [
                    'iframe[src*="consent.google.com"]',
                    'iframe[src*="fundingchoicesmessages"]'
                ]
                
                for selector in google_consent_selectors:
                    iframe_element = await page.querySelector(selector)
                    if iframe_element:
                        # Get frame directly from iframe element
                        frame_handle = await iframe_element.contentFrame()
                        if frame_handle:
                            # Common consent button selectors
                            consent_button_selectors = [
                                'button[aria-label="Tout accepter"]',
                                'button[aria-label="Accept all"]',
                                'button.pw6PMc',  # Google's consent button class
                                'button[aria-label="Agree to the use of cookies and other data for the purposes described"]'
                            ]
                            
                            for button_selector in consent_button_selectors:
                                try:
                                    button = await frame_handle.querySelector(button_selector)
                                    if button:
                                        await button.click()
                                        await asyncio.sleep(2)  # Wait longer after consent
                                        return
                                except Exception as e:
                                    logging.warning(f"Failed to click consent button {button_selector}: {e}")
                                    continue
                
            except Exception as e:
                logging.warning(f"Error handling popups: {e}")
                # Continue even if popup handling fails
                pass
        
        # Try to handle popups
        await handle_popups()
        
        # Remove navigation bar
        await page.evaluate('document.querySelector("nav")?.remove()')
        
        # Wait a bit longer after handling popups
        await asyncio.sleep(2)
        
        # Check if the main content is visible
        hit_element = await page.querySelector('annonces-post-detail > div')
        
        if hit_element is None:
            logging.warning(f"Main content element not found for {current_hit['slug']}")
            # Take full page screenshot as fallback
            await page.screenshot({'path': current_hit['slug']+'.png'})
            result = None
        else:
            # Additional check for any remaining overlay elements
            await page.evaluate('''
                () => {
                    // Remove any remaining overlay elements
                    const overlays = document.querySelectorAll('[id*="consent"], [class*="consent"], [id*="cookie"], [class*="cookie"]');
                    overlays.forEach(overlay => overlay.remove());
                }
            ''')
            
            # Wait a moment for any remaining animations
            await asyncio.sleep(1)
            result = await hit_element.screenshot(encoding="base64")
        
        return result
        
    except Exception as e:
        logging.warning(f"Screenshot failed: {e}")
        return None
        
    finally:
        if 'page' in locals():
            await page.close()


db = TinyDB(Path(__file__).with_name('db.json'))
processedAdsTable = db.table('processed')

header = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
        "Accept": "application/vnd.wamland+json; version=1",
        "Accept-Language": "en-US,en;q=0.5",
        "Connection": "keep-alive",
        "Host":"api.annonces.nc",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "no-cors",
        "Sec-Fetch-Site": "same-site",
        "Sec-GPC": "1",
        "If-None-Match": "W/\"fe5873a8a05044232d81be69f50e46b8\"",
        "Priority": "u=4",
        "Pragma": "no-cache",
        "Cache-Control": "no-cache",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Origin": "https://annonces.nc",
        "Referer": "https://annonces.nc/",
        "Sec-Ch-Ua-Mobile": "?1",
        "Sec-Ch-Ua-Platform": "Android",
        "Sec-Fetch-Site": "same-site",
        "Sec-Gpc": "1"
    }

url = "https://api.annonces.nc/posts/search"

async def process():
    global browser
    browser = await launch(ignoreHTTPSErrors = True, options = {'args': ['--no-sandbox']})
#    browser = await launch(ignoreHTTPSErrors = True, options = {'args': ['--no-sandbox'], 'headless': False })
#    browser = await launch()
    for x in config:
        global current_config
        current_config = x
        for search in x['searches']:
            global current_search
            current_search = search
            page = 0
            while (True):
                params = {
                    "by_text": search['keywords'],
                    "page": page
                }
                #data = {"params" : urllib.parse.urlencode(params)}
                #response = requests.post('http://gvle5z29mr-dsn.algolia.net/1/indexes/Post/query?' + urllib.parse.urlencode(url), data = json.dumps(data))
                response = requests.get(url, params=params, headers=header, verify=False)
                results = response.json()
                if len(results) == 0:
                    break
                for hit in results:
                    global current_hit
                    current_hit = hit
                    await process_hit()
                page = page + 1
    await browser.close()
    logging.info('finish process')

asyncio.run(process())


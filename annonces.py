import requests
import json
import urllib
from tinydb import TinyDB, where
from mailjet_rest import Client

categories_to_remove = {
    "automobiles.nc": ["Divers", "Pièces moteurs", "Carrosseries", "Éclairages"],
    "2roues.nc": ["Pièces détachées Moto"]
}    

with open('config.json', 'r') as f:
  config = json.load(f)

with open('mail-config.json', 'r') as f:
  mail_config = json.load(f)

def filter_hit():
    if hit['kind'] != "sell" or  hit['category']['root_name'] != search['site'] or hit['category']['name'] in categories_to_remove[search['site']]:
        return False
    if search.get('max_km') and hit['custom_fields'].get('km') and hit['custom_fields']['km'] > search['max_km']:
        #the hit as too much mileage
        return False
    return True

def send_email():
    api_key = mail_config['MailJet']['Api_Key']
    api_secret = mail_config['MailJet']['Api_Secret']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')
    data = {
    'Messages': [
        {
        "From": mail_config['MailJet']['From'],
        "To": [
            {
            "Email": x['email']
            }
        ],
        "Subject": "New add on automobiles.nc for your search " + search['keywords'],
        "TextPart": 'https://annonces.nc/automobiles/posts/'+hit['slug'],
        "HTMLPart": "<a href=\"https://annonces.nc/automobiles/posts/"+hit['slug']+"\">Click here</a></li>",
        }
    ]
    }
    result = mailjet.send.create(data=data)

def process_new_hit():
    processedAdsTable.insert({'search_id': search['id'] , 'hit_id': hit['id']})
    if filter_hit() == True:
        print(hit)
        send_email()
    print('new ad! '  + str(search['id']) + ' ' + str(hit['id']))

def process_hit():
    query = processedAdsTable.get((where('hit_id') == hit['id']) & (where('search_id') == search['id']))
    if query is None:
        process_new_hit()        
    else:
        print('skipping ad ' + str(hit['id']))

db = TinyDB('db.json')
processedAdsTable = db.table('processed') 

url = {
    "x-algolia-agent": "Algolia for JavaScript (3.35.1); Browser",
    "x-algolia-application-id": "GVLE5Z29MR",
    "x-algolia-api-key": "fa6c9390760eb58e3197d2689a2a16f9"
}

for x in config:
    for search in x['searches']:                
        page = 0
        while (True):
            params = {
                "query": search['keywords'],
                "page": page
            }
            data = {"params" : urllib.parse.urlencode(params)}
            response = requests.post('https://gvle5z29mr-dsn.algolia.net/1/indexes/Post/query?'+urllib.parse.urlencode(url), data=json.dumps(data), verify=False)
            results = response.json()
            if len(results['hits']) == 0:
                break
            for hit in results['hits']:                
                process_hit()
            page = page + 1

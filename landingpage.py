""" version 2 """
import json
import boto3
import msal
import os
import requests
from jinja2 import Environment
from jinja2_s3loader import S3loader

# reading details
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('cisco-metadata-details')
table_tokens = dynamodb.Table('access_tokens')

# single tenant app details from DB
s_app_item = table.get_item(
        Key ={"app": "single-tenant-app"}
    )
s_app_details = s_app_item.get("Item")

# multi tenant app details from DB
m_app_item = table.get_item(
        Key ={"app": "multi-tenant-app"}
    )
m_app_details = m_app_item.get("Item")

# to get Oauth-flow-values from DB
client = boto3.client('dynamodb')

# Bulid app object and initiate auth code
def _build_msal_app(cache=None, authority=None):
    return msal.ConfidentialClientApplication(
        m_app_details.get("clientId"), authority=m_app_details.get("authority"),
        client_credential=m_app_details.get("client_secret"), token_cache=cache)

# fetching state value
def getflow(state):
    
    data = client.get_item(
        TableName='Oauth-flow-values',
        Key={
            'state':{"S":state}}
    )
    return data

# deleting flow value
def delete_flow(state):
    table = dynamodb.Table('Oauth-flow-values')
    response = table.delete_item(
        Key={
            'state': state
        }
    )
    if response:
        return True
    else:
        return False
        
# get access token(for graph api) if already exists 
def get_token_from_dynamo_db(state):
    result_state = table_tokens.get_item(
            Key ={"state": state}
        )
    result = result_state.get("Item")
    return result

# save access token(for graph api) if doesn't exist
def save_the_result_into_dynamo_db(state, result):
    print(table_tokens.table_status)
    table_tokens.put_item(Item= {'state': state,'result':  result})

# renders landing page with user information
def lambda_handler(event, context):
    
    query_params = event["queryStringParameters"]
    state = query_params["state"]
    data = getflow(state)
    flow = json.loads(data["Item"]['flow']["S"])
    purchase_id_token = data["Item"]['purchase_id_token']["S"]
    
    # access token for graph api
    result = get_token_from_dynamo_db(state)
    if result is None:
        result = _build_msal_app().acquire_token_by_auth_code_flow(
            flow, query_params
        )
        save_the_result_into_dynamo_db(state, result)
        # calling graph apis
        graph_data = requests.get(
            m_app_details.get("endpoint"),
            headers={'Authorization': 'Bearer ' + result['access_token'] }
            ).json()
            
    else:
        # calling graph apis
        graph_data = requests.get(
            m_app_details.get("endpoint"),
            headers={'Authorization': 'Bearer ' + result['result']['access_token'] }
            ).json()
        

    # get the subscription details related to purchase_id_token
    response= resolveSubscriptionDetails(purchase_id_token)
    # response["offerId"] = "App-D"

    res_dict = {
        "first_name": graph_data["givenName"],
        "last_name": graph_data["surname"],
        "user_principal_name": graph_data["userPrincipalName"],
        "subscription_id": response["id"],
        "subscription_name": response["subscriptionName"], 
        "offer_id": response["offerId"],
        "plan_id": response["planId"],
        "beneficiaryemail_id": response["subscription"]["beneficiary"]["emailId"],
        "purchaseremail_id": response["subscription"]["purchaser"]["emailId"],
        "publisher_id": response["subscription"]["publisherId"],
        "saas_subscription_status" : response["subscription"]["saasSubscriptionStatus"],
        "term_unit" : response["subscription"]["term"]["termUnit"],
        "auto_renew" : response["subscription"]["autoRenew"],
        "is_test" : response["subscription"]["isTest"],
        "is_free_trial" : response["subscription"]["isFreeTrial"],
        "created" : response["subscription"]["created"],
        "last_modified" : response["subscription"]["lastModified"],
        
    }
    
    # loading html dynamic content based on offer
    html_content = html_loader(response["offerId"], res_dict)
    
    # is_flow = delete_flow(state)
    # print("delete flow value", is_flow)
    
    return {
        "statusCode": 200,
        "body": html_content,
        "headers": {
            "Content-Type": "text/html",
        }
    }

def resolveSubscriptionDetails(purchase_id_token):
    access_token = getAccessToken()
    responseStatus = resolveSubscription( purchase_id_token, access_token)
    return responseStatus
    
def getAccessToken():
    
    url = "https://login.microsoftonline.com/" + s_app_details.get("tenantId") + "/oauth2/token"

    data = {
        "client_id":s_app_details.get("clientId"),
        "resource":s_app_details.get("resource"),
        "client_secret" : s_app_details.get("client_secret"),
        "grant_type" : s_app_details.get("grant_type")
    }
    
    r = requests.post(url, data)
    access_token = r.json()["access_token"]
    
    return access_token
    
def resolveSubscription(purchase_id_token, access_token):
    
    url = "https://marketplaceapi.microsoft.com/api/saas/subscriptions/resolve?api-version=2018-08-31"
    authorization_token = "Bearer" + " " + access_token
    purchase_id_token_decrypt = requests.utils.unquote(purchase_id_token)
    
  
    data = {
        "x-ms-marketplace-token" : purchase_id_token_decrypt,
        "Content-Type" : "application/json",
        "Authorization" : authorization_token
    }
            
    r= requests.post(url, headers=data)
        
    response = r.json()
    
    return response
    
def html_loader(offerId, res_dict):
    
    template_dict = {
        "xor-test-offer-preview": 'index5.html',
        "App-D": 'index4.html',
        "error": 'error_dummy.html',
    }
    
    if res_dict["user_principal_name"] == res_dict["beneficiaryemail_id"] or res_dict["user_principal_name"] == res_dict["purchaseremail_id"] :
        template = template_dict.get(offerId, "index.html")
    else:
        template = template_dict.get("error")
    s3template_dir = "templates"
    env = Environment(loader=S3loader('test-sattic-lp', s3template_dir))
    temp = env.get_template(template)  
    html_content = temp.render(res_dict)
    
    return html_content
    
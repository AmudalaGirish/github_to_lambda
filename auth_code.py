# version 2

import json
import boto3
import msal
import os
import logging

# reading details
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('cisco-metadata-details')

# multi tenant app details from DB
m_app_item = table.get_item(
        Key ={"app": "multi-tenant-app"}
    )
m_app_details = m_app_item.get("Item")

# client creation for dynamoDB
client = boto3.client(
    'dynamodb')

# Bulid app object and initiate auth code
def _build_msal_app(cache=None, authority=None):
    return msal.ConfidentialClientApplication(
        m_app_details.get("clientId"), authority=m_app_details.get("authority"),
        client_credential=m_app_details.get("client_secret"), token_cache=cache)
        
def _build_auth_code_flow(authority=None, scopes=None):
    return _build_msal_app(authority=authority).initiate_auth_code_flow(
        scopes or [] ,
        redirect_uri=m_app_details.get("redirect_uri"))


# redirects to azure login page
def lambda_handler(event, context):
    
    # capture purchase_id 
    purchase_ID = event["queryStringParameters"]['token']
    
    scope_list = m_app_details.get("scope")
    scope_list = [eval(el) for el in scope_list]

    flow = _build_auth_code_flow(scopes=scope_list)
    
    # saving flow in dynamoDB
    data = client.put_item(
        TableName='Oauth-flow-values',
        Item={
            'state': {'S':flow["state"]},
            'flow':{"S":json.dumps(flow)},
            'purchase_id_token':{"S":purchase_ID}
        }
    )
    
    redirect_uri = flow["auth_uri"]
    
    # redirecting to azure login url
    response = {
        'headers':{"Location":redirect_uri},
        'statusCode':301,
    }
    return response

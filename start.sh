#!/bin/bash

cd spug_api
source venv/bin/activate
python manage.py runserver

cd spug_web
nvm use v18
export NODE_OPTIONS=--openssl-legacy-provider
npm start

redis-server
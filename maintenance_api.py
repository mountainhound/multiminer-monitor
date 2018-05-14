from flask import Flask, request, jsonify, url_for
from gevent.wsgi import WSGIServer
import requests
from bandwidth import messaging
import json
import datetime
import pytz
import time
from decimal import *
import signal
import sys
import os

import logging
logging.basicConfig()

import settings as settings
from flask_apscheduler import APScheduler
#from apscheduler.schedulers.background import BackgroundScheduler


app = Flask(__name__)

def miner_check(): 
	alarm_dict = {}
	stop_list = []
	with app.app_context():
		for key,url in settings.MINER_IPS.items():
			try: 
				print "GET"
				ret = requests.get(url+"/miner_stats")
				status_code = ret.status_code
				if status_code == 200: 
					temps = ret.json().get('data').get('temps')
					for temp in temps: 
						temp = temp.replace("C","")
						temp = int(temp)
						if temp > settings.ALARM_TEMP: 
							alarm_dict[key] = str(temp)+"C"
						if temp > settings.MAX_TEMP: 
							stop_list.append(key)

				if alarm_dict: 
					alarm = "TEMP ALARM: \n {}".format(alarm_dict)
					for number in settings.ROOT_NUMBERS:
						text_message(app.config['MESSAGE_API'],alarm,number) 
				if stop_list: 
					ret = stop_miner(stop_list,settings.MINER_IPS)
					text_str = "Attemping to Stop Temp Over {} C: \nMiners: {} \nResult: {}".format(settings.MAX_TEMP,stop_list,ret)
					for number in settings.ROOT_NUMBERS:
						text_message(app.config['MESSAGE_API'],text_str,number)

			except Exception as err: 
				print err
				
		return None

class Config(object):
	JOBS = [
			{
				'id': 'Miner Bot Maintenance',
				'func': miner_check,
				'trigger': 'interval',
				'seconds': 10,
				'max_instances': 1
			}
	]

	SCHEDULER_API_ENABLED = True

'''
def sigint_handler(signum, frame):
	time.sleep(1)
	sys.exit()
 
signal.signal(signal.SIGINT, sigint_handler)
'''

def create_app():
	app.config['LOG_PATH'] = "stat-log.json"
	app.config['MESSAGE_API'] = messaging.Client(settings.BANDWIDTH_USER, settings.BANDWIDTH_TOKEN, settings.BANDWIDTH_SECRET)
	app.config['ROOT_NUMBERS'] = settings.ROOT_NUMBERS
	app.config['MINER_IPS'] = settings.MINER_IPS
	
	app.config.from_object(Config())
	return app

def text_message(message_api,message_body,sender_num):

	message_id = message_api.send_message(from_ = '+{}'.format(settings.ORIGIN_NUMBER),
                              to = '+{}'.format(sender_num),
                              text = message_body)

def logger(log_path,log_message):
	utc_now = pytz.utc.localize(datetime.datetime.utcnow())
	#pst_now = utc_now.astimezone(pytz.timezone("America/Los_Angeles"))
	ct_now = utc_now.astimezone(pytz.timezone("America/Chicago"))
	log_message['central-timezone'] = str(ct_now.isoformat())
	
	with open(log_path,'a+') as f:
		json.dump(log_message, f)
		f.write('\n')

def miner_stat_parser(key,body,status):
	data = body.get('data')
	temps = data.get('temps')
	hashrate = data.get('hashrate')
	unit = data.get('hashrate_unit')
	algo = data.get('algo')
	gpu_num = data.get('gpu_num')

	response_str = "Miner_{}_Stats: \n Temps:{} \n Hashrate:{}{} \n Algo:{} \n GPU_Num:{} \n Status Code: {}".format(key,temps,hashrate,unit,algo,gpu_num,status)

	return response_str


def miner_stats(miner_list,miner_ips):
	response_code_dict = {}
	response_body_dict = {}

	print miner_list
	if not miner_list: 
		for key,url in miner_ips.items():
			try: 
				print "GET"
				ret = requests.get(url+"/miner_stats")
				status_code = ret.status_code
				response_code_dict[key] = ret.status_code
				print ret.json()
				response_str = miner_stat_parser(key,ret.json(),status_code)
				response_body_dict[key] = response_str
			except Exception as err: 
				print err
				response_body_dict[key] = "Miner_{}_Stats: \n Error: {}".format(key,err)
	else:
		for key,url in miner_ips.items():
			print key
			if key in miner_list:
				try: 
					ret = requests.get(url+"/miner_stats")
					status_code = ret.status_code
					response_code_dict[key] = ret.status_code 
					response_str = miner_stat_parser(key,ret.json(),status_code)
					response_body_dict[key] = response_str
				except Exception as err: 
					print err
					response_body_dict[key] = "Miner_{}_Stats: \n Error: {}".format(key,err)

	return response_body_dict

def stop_miner(miner_list,miner_ips):
	response_code_dict = {}
	if not miner_list: 
		for key,url in miner_ips.items():
			try: 
				data = {"mode":"stop"}
				ret = requests.post(url+"/mining_mode",data = data)
				response_code_dict[key] = ret.status_code
			except Exception as err:
				print err 
				response_code_dict[key] = "Error: {}".format(err)
	else: 
		for key,url in miner_ips.items():
			if key in miner_list:
				try: 
					data = {"mode":"stop"}
					ret = requests.post(url+"/mining_mode",data = data)
					response_code_dict[key] = ret.status_code
				except Exception as err: 
					print err
					response_code_dict[key] = "Error: {}".format(err)

	return response_code_dict

def start_miner(miner = None):
	pass

@app.route('/stats', methods=['POST'])
def stats():
	app.config['ROOT_FLAG'] = False
	
	data =  request.data
	data = json.loads(data)
	message_body = data.get('text').lower()
	number = data.get('from')
	number = number.replace("+","").replace("(","").replace(")","")
	root_numbers = app.config['ROOT_NUMBERS']
	message_api = app.config['MESSAGE_API']
	miner_ips = app.config['MINER_IPS']


	if number in root_numbers:
		print "HELLO ROOT USER"
	else: 
		print number
		return "NOT AUTHORIZED", 403

	print message_body

	if "shutdown" in message_body or "stop" in message_body:
		miner_list = []
		print "SHUTTING DOWN MINER"
		for key,value in miner_ips.items():
			if str(key) in message_body:
				miner_list.append(key)

		response_dict = stop_miner(miner_list,miner_ips)

		text_message(message_api,"MINER RESPONSES: {} \n".format(response_dict),number) 


	if "status" in message_body or "stats" in message_body: 
		miner_list = []
		print "MINER STATS"
		for key,value in miner_ips.items():
			if str(key) in message_body:
				miner_list.append(key)

		response_dict = miner_stats(miner_list,miner_ips)

		for key,body in response_dict.items():
			text_message(message_api, body,number) 

	return str(message_body)

if __name__ == '__main__':
	app = create_app()
	
	scheduler = APScheduler()
	scheduler.init_app(app)
	scheduler.start()
	
	'''
	sched = BackgroundScheduler(daemon=True)
	sched.add_job(maintenance,'interval',seconds=10)
	sched.start()
	'''
	#app.run(port = 5000,threaded = True)
	app.run(port = 5000)

	#http_server = WSGIServer(('',5000),app)
	#http_server.serve_forever()


#!/usr/bin/env python3
#
# Author:
#  Tamas Jos (@skelsec)
#

import os
import json
import glob
import ntpath
import traceback
import asyncio
import base64

from pypykatz import logger
from pypykatz.apypykatz import apypykatz
from pypykatz.commons.common import UniversalEncoder
from pypykatz.alsadecryptor.packages.msv.decryptor import LogonSession



class LSACMDHelper:
	def __init__(self):
		self.live_keywords = ['lsa']
		self.keywords = ['lsa']
		
	def add_args(self, parser, live_parser):
		group = parser.add_parser('lsa', help='Get secrets from memory dump')
		group.add_argument('cmd', choices=['minidump','rekall'])
		group.add_argument('memoryfile', help='path to the dump file')
		group.add_argument('-t','--timestamp_override', type=int, help='enforces msv timestamp override (0=normal, 1=anti_mimikatz)')
		group.add_argument('--json', action='store_true',help = 'Print credentials in JSON format')
		group.add_argument('-e','--halt-on-error', action='store_true',help = 'Stops parsing when a file cannot be parsed')
		group.add_argument('-o', '--outfile', help = 'Save results to file (you can specify --json for json file, or text format will be written)')
		group.add_argument('-k', '--kerberos-dir', help = 'Save kerberos tickets to a directory.')
		group.add_argument('-r', '--recursive', action='store_true', help = 'Recursive parsing')
		group.add_argument('-d', '--directory', action='store_true', help = 'Parse all dump files in a folder')
		group.add_argument('-g', '--grep', action='store_true', help = 'Print credentials in greppable format')
		group.add_argument('-p','--packages', choices = ['all','msv', 'wdigest', 'tspkg', 'ssp', 'livessp', 'dpapi', 'cloudap'], nargs="+", default = 'all', help = 'LSASS package to parse')

		
	def execute(self, args):
		if len(self.keywords) > 0 and args.command in self.keywords:
			asyncio.run(self.run(args))
		
		if len(self.live_keywords) > 0 and args.command == 'live' and args.module in self.live_keywords:
			self.run_live(args)
			
	def process_results(self, results, files_with_error, args):
		if args.outfile and args.json:
			with open(args.outfile, 'w') as f:
				json.dump(results, f, cls = UniversalEncoder, indent=4, sort_keys=True)

		elif args.outfile and args.grep:
			if '../' in args.outfile or '..\\' in args.outfile:
				raise Exception('Invalid file path')
			with open(args.outfile, 'w', newline = '') as f:
				f.write(':'.join(LogonSession.grep_header) + '\r\n')
				for result in results:
					for luid in results[result].logon_sessions:
						for row in results[result].logon_sessions[luid].to_grep_rows():
							f.write(':'.join(row) + '\r\n')
		
		elif args.outfile:
			if '../' in args.outfile or '..\\' in args.outfile:
				raise Exception('Invalid file path')
			with open(args.outfile, 'w') as f:
				for result in results:
					f.write('FILE: ======== %s =======\n' % result)
					
					for luid in results[result].logon_sessions:
						f.write('\n'+str(results[result].logon_sessions[luid]))
					
					if len(results[result].orphaned_creds) > 0:
						f.write('\n== Orphaned credentials ==\n')
						for cred in results[result].orphaned_creds:
							f.write(str(cred))
					
				if len(files_with_error) > 0:
					f.write('\n== Failed to parse these files:\n')
					for filename in files_with_error:
						f.write('%s\n' % filename)
						
		elif args.json:
			print(json.dumps(results, cls = UniversalEncoder, indent=4, sort_keys=True))
		
		elif args.grep:
			if args.directory:
				print(':'.join(['filename'] + LogonSession.grep_header))
			else:
				print(':'.join(LogonSession.grep_header))
			for result in results:
				for luid in results[result].logon_sessions:
					for row in results[result].logon_sessions[luid].to_grep_rows():
						if args.directory:
							row = [result] + row
						print(':'.join(row))
				for cred in results[result].orphaned_creds:
					t = cred.to_dict()
					if t['credtype'] != 'dpapi':
						if t['password'] is not None:
							x =  [str(t['credtype']), str(t['domainname']), str(t['username']), '', '', '', '', '', str(t['password'])]
							if args.directory:
								x = [result] + x
							print(':'.join(x))
					else:
						t = cred.to_dict()
						x = [str(t['credtype']), '', '', '', '', '', str(t['masterkey']), str(t['sha1_masterkey']), str(t['key_guid']), '']
						if args.directory:
							x = [result] + x
						print(':'.join(x))

				for pkg, err in results[result].errors:
					err_str = str(err) +'\r\n' + '\r\n'.join(traceback.format_tb(err.__traceback__))
					err_str = base64.b64encode(err_str.encode()).decode()
					x =  [pkg+'_exception_please_report', '', '', '', '', '', '', '', '', err_str]
					if args.directory:
						x = [result] + x
					print(':'.join(x) + '\r\n')

		else:
			for result in results:
				print('FILE: ======== %s =======' % result)	
				if isinstance(results[result], str):
					print(results[result])
				else:
					for luid in results[result].logon_sessions:
						print(str(results[result].logon_sessions[luid]))
							
					if len(results[result].orphaned_creds) > 0:
						print('== Orphaned credentials ==')
						for cred in results[result].orphaned_creds:
							print(str(cred))
					
					if len(results[result].errors) > 0:
						print('== Errors ==')
						for pkg, err in results[result].errors:
							err_str = str(err) +'\r\n' + '\r\n'.join(traceback.format_tb(err.__traceback__))
							err_str = base64.b64encode(err_str.encode()).decode()
							print('%s %s' % (pkg+'_exception_please_report',err_str))
					

			if len(files_with_error) > 0:			
				print('\n==== Parsing errors:')
				for filename in files_with_error:
					print(filename)
		
		
		if args.kerberos_dir:
			dir = os.path.abspath(args.kerberos_dir)
			logger.info('Writing kerberos tickets to %s' % dir)
			for filename in results:
				base_filename = ntpath.basename(filename)
				ccache_filename = '%s_%s.ccache' % (base_filename, os.urandom(4).hex()) #to avoid collisions
				results[filename].kerberos_ccache.to_file(os.path.join(dir, ccache_filename))
				for luid in results[filename].logon_sessions:
					for kcred in results[filename].logon_sessions[luid].kerberos_creds:
						for ticket in kcred.tickets:
							ticket.to_kirbi(dir)
							
				for cred in results[filename].orphaned_creds:
					if cred.credtype == 'kerberos':
						for ticket in cred.tickets:
							ticket.to_kirbi(dir)
		
	def run_live(self, args):
		return
			
	async def run(self, args):
		files_with_error = []
		results = {}
		###### Minidump
		if args.cmd == 'minidump':
			if args.directory:
				dir_fullpath = os.path.abspath(args.memoryfile)
				for file_pattern in ['*.dmp', '*.DMP']:
					if args.recursive == True:
						globdata = os.path.join(dir_fullpath, '**', file_pattern)
					else:
						globdata = os.path.join(dir_fullpath, file_pattern)
					
					logger.info('Parsing folder %s' % dir_fullpath)
					for filename in glob.glob(globdata, recursive=args.recursive):
						logger.info('Parsing file %s' % filename)
						try:
							mimi = await apypykatz.parse_minidump_file(filename, packages = args.packages)
							results[filename] = mimi
						except Exception as e:
							files_with_error.append(filename)
							logger.exception('Error parsing file %s ' % filename)
							if args.halt_on_error == True:
								raise e
							else:
								pass
					
			else:
				logger.info('Parsing file %s' % args.memoryfile)
				try:
					mimi = await apypykatz.parse_minidump_file(args.memoryfile, packages = args.packages)
					results[args.memoryfile] = mimi
				except Exception as e:
					logger.exception('Error while parsing file %s' % args.memoryfile)
					if args.halt_on_error == True:
						raise e
					else:
						traceback.print_exc()
						
		self.process_results(results, files_with_error, args)
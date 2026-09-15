#!/usr/bin/python3
"""Resolve exact installed/candidate versions from configured apt metadata; no writes."""
import subprocess,re
from ansible.module_utils.basic import AnsibleModule

def main():
 m=AnsibleModule(argument_spec={'packages':{'type':'list','elements':'str','required':True}},supports_check_mode=True)
 result={}
 for package in m.params['packages']:
  if not re.fullmatch(r'[a-z0-9][a-z0-9+.-]*',package):m.fail_json(msg='Invalid package name')
  r=subprocess.run(['apt-cache','policy',package],text=True,capture_output=True,env={'PATH':'/usr/bin:/bin','LC_ALL':'C'},timeout=30)
  installed=re.search(r'^\s*Installed:\s*(\S+)',r.stdout,re.M);candidate=re.search(r'^\s*Candidate:\s*(\S+)',r.stdout,re.M)
  value=installed.group(1) if installed and installed.group(1)!='(none)' else candidate.group(1) if candidate else '(none)'
  if r.returncode or value=='(none)' or not re.fullmatch(r'[a-zA-Z0-9.+:~_-]+',value):m.fail_json(msg='No approved repository candidate for '+package)
  result[package]=value
 m.exit_json(changed=False,versions=result)
if __name__=='__main__':main()

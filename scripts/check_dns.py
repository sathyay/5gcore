import subprocess

def run(cmd):
    return subprocess.getoutput(cmd)

output = run("kubectl exec deploy/oai-gnb -n oai5g -- getent hosts oai-amf")

print("DNS OUTPUT:", output)

if "10." not in output:
    raise Exception("DNS resolution failed for AMF")

print("DNS OK")

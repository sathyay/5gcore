import subprocess
from pyats import aetest

class DNSCheck(aetest.Testcase):

    @aetest.test
    def resolve_amf(self):
        cmd = "kubectl exec deploy/oai-gnb -n oai5g -- getent hosts oai-amf"
        output = subprocess.getoutput(cmd)

        assert "10." in output

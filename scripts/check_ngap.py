import subprocess
from pyats import aetest

class NGAPCheck(aetest.Testcase):

    @aetest.test
    def check_ngap_logs(self):
        cmd = "kubectl logs deploy/oai-gnb -n oai5g | grep NGAP"
        output = subprocess.getoutput(cmd)

        assert "check the amf registration state" in output

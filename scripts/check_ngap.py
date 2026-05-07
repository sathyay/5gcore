import subprocess
from pyats import aetest

class NGAPCheck(aetest.Testcase):

    @aetest.test
    def check_ngap_logs(self):
        cmd = "kubectl logs deploy/oai-gnb -n oai5g | grep NGAP"
        output = subprocess.getoutput(cmd)

        print("\n================ NGAP VALIDATION =================")

        if "check the amf registration state" in output:
            print("✅ NGAP STATUS: PASS")
            print("✔ AMF registration check message found in logs")
            print("✔ gNB ↔ AMF NGAP signaling is healthy")
        else:
            print("❌ NGAP STATUS: FAIL")
            print("✖ AMF registration state not found")
            print("✖ Possible issues: routing / AMF unreachable / SCTP failure")

        print("===================================================\n")

        assert "check the amf registration state" in output

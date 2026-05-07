from pyats import aetest
import subprocess

class UEAttach(aetest.Testcase):

    @aetest.test
    def check_ue_attach(self):
        print("\n================ UE ATTACH VALIDATION =================")

        cmd = "kubectl logs deploy/oai-nr-ue -n oai5g | grep -i 'RRCSetupComplete'"
        output = subprocess.getoutput(cmd)

        if "RRCSetupComplete" in output:
            print("✅ UE ATTACH STATUS: PASS")
            print("✔ UE successfully completed RRC connection")
            print("✔ UE is attached to 5G core")
        else:
            print("❌ UE ATTACH STATUS: FAIL")
            print("✖ UE attach not completed")
            print("✖ Check NGAP / AMF / gNB connectivity")

        print("=====================================================\n")

        assert "RRCSetupComplete" in output

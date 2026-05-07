class UEAttach(aetest.Testcase):

    @aetest.test
    def ue_attach(self):
        logs = subprocess.getoutput(
            "kubectl logs deploy/oai-amf -n oai5g | grep REGISTERED"
        )

        assert "5GMM-REGISTERED" in logs

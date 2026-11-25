from iteration_wallet import cli

def test_cli_session_declares_human_intent_method(monkeypatch):
    seen={}
    def fake(method,path,payload=None,**kwargs):
        seen.update(payload or {})
        return {'session_id':'s'}
    monkeypatch.setattr(cli,'_req',fake)
    cli._start_session('judge',60)
    assert 'human_ceremony' in seen['verified_methods']

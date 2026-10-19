from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from consumer.app import app
from shared.models import Offer, Intent, ScoredOffer
from shared.assurance import assess, price_gap
from shared.recipe_contracts import RecipeEvidence, shortage
from shared.nlu import rule_nlu
from shared.engines.commerce_ai_adapter import CommerceAIEngine
from shared.engines.recommender import apply_budget
from b2b.supplier_contracts import SupplierEvidence


def test_recipe_source_keeps_both_expressions():
    r = RecipeEvidence(source_id='RC061', raw_text='손가락 1마디 반정도크기 150g').quantities()
    assert r['explicit_quantities'] == ['150g'] and r['new_conversions'] is None
    assert '손가락' in r['raw_text'] and r['cooking_state'] is None


def test_recipe_state_blocks_conversion():
    assert shortage(100, 200, 'g', 'g', 'dry', 'cooked')['shortage'] is None
    assert shortage(100, 20, 'g', 'g', 'dry', 'dry')['shortage'] == 80


def test_recipe_endpoint_optional_and_required():
    ingredient = dict(name='면', quantity=100, unit='g', cooking_state='dry', owned=20,
                      owned_unit='g', owned_state='dry', evidence={'source_id':'user', 'raw_text':'마른 면 100g'})
    c = TestClient(app)
    r = c.post('/api/recipe/plan', json={'title':'파스타', 'ingredients':[ingredient]}).json()
    assert r['missing_required'][0]['shortage'] == 80 and r['shopping_dispatch'] is False
    ingredient['required'] = False
    assert not c.post('/api/recipe/plan', json={'title':'파스타', 'ingredients':[ingredient]}).json()['missing_required']


def test_recipe_chat_does_not_search_products():
    r = TestClient(app).post('/api/chat', json={'message':'파스타 레시피 알려줘'}).json()
    assert r['stage'] == 'clarify'
    assert all(b['type'] != 'product_list' for b in r['blocks'])


def test_nlu_preserves_gift_trust_allergen():
    s = rule_nlu.parse('쿠팡 부모님 어버이날 선물 사과 후기 많은 것').slots
    assert s['priority'] == 'trust' and s['purpose'] == 'gift'
    assert s['recipient'] == 'senior' and s['occasion'] == 'parents_day'
    assert rule_nlu.parse('쿠팡 글루텐 없는 과자').slots['allergen'] == 'gluten'


def test_unknown_shipping_never_total_unit_price():
    o = Offer(mall='x', title='x', price=10, unit_count=2)
    assert o.unit_price is None and assess(o)['status'] == 'NOT_RANKABLE'
    row = ScoredOffer(offer=o)
    assert apply_budget([row], Intent(slots={'budget_max':20}))[0].unverified


def test_score_zero_precedence():
    r = CommerceAIEngine._to_scored({'name':'a','v7_final_score':0,'score':99})
    assert r.score == 0 and r.score_source == 'v7_final_score'


def test_price_gap_quality_guard():
    a = Offer(mall='x',title='a',price=10,shipping_fee=0)
    b = Offer(mall='y',title='a',price=20,shipping_fee=0)
    assert price_gap(a,b)['status'] == 'NOT_COMPARABLE'
    for x in (a,b):
        x.variant_id='same'; x.weight_g=1000; x.origin='KR'; x.grade='상품'
    assert price_gap(a,b)['status'] == 'PRICE_INVERSION'


def test_quote_expires():
    s = SupplierEvidence(supplier_id='s',name='s',source_ref='source', business_status_confirmed=True,
                         species=['소'],spec='1kg',quantity=2,quote_price=100,delivery_confirmed=True,
                         quote_expires_at=datetime.now(timezone.utc)-timedelta(days=1))
    assert s.evaluate()['status'] == 'DISCOVERY_ONLY'


def test_sufficiency_and_expiry():
    o = Offer(mall='x',title='x',price=10,shipping_fee=0,variant_id='v',return_policy='7일',
              delivery_terms='2일',source_refs=['original'])
    assert assess(o)['status'] == 'RANKABLE'
    assert assess(o,now=o.observed_at+timedelta(days=2))['status'] == 'NOT_RANKABLE'

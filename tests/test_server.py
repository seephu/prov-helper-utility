import os
import pytest

from loguru import logger
from flask import session

from difflib import SequenceMatcher
from server import server, SERVED_FILES_DIR, setup_session


@pytest.fixture(scope='module')
def app():
    app = server
    app.config['TESTING'] = True

    # other setup can go here
    yield app
    # clean up / reset resources here


@pytest.fixture()
def client(app):
    test_client = app.test_client()
    test_client.routes = {
        'internet': '/commercial/configgen/internet',
        'transparent_lan': '/commercial/configgen/transparent_lan',
        'layer2_test': '/commercial/configgen/layer2_test',
        'raisecom': '/commercial/configgen/raisecom',
        'login': '/login'
    }
    test_client.get('/')  # Sets up session variables
    return test_client


@pytest.mark.parametrize('route, form', [
    ('internet', 'bgp1'),
    ('internet', 'bgp2'),
    ('internet', 'isis1'),
    ('internet', 'isis2'),
    ('transparent_lan', 'transparent_lan1'),
    ('layer2_test', 'layer2_test'),
    ('raisecom', 'raisecom1')
])
def test_configgen_get(client, route, form, request):
    # Verify fixture form correlates with HTML elements
    circuit = request.getfixturevalue(form)
    response = client.get(client.routes[route])
    form_inputs = circuit.form.html
    form_inputs.pop('circuitType')  # circuit_type gets manually added in Flask route
    for ele in form_inputs.keys():
        assert ele in response.data.decode()


@pytest.mark.parametrize('route, form', [
    ('internet', 'bgp1'),
    ('internet', 'bgp2'),
    ('internet', 'isis1'),
    ('internet', 'isis2'),
    ('transparent_lan', 'transparent_lan1'),
    ('layer2_test', 'layer2_test'),
    ('raisecom', 'raisecom1')
])
def test_configgen_post(client, route, form, request):
    # POST form data
    circuit = request.getfixturevalue(form)
    response = client.post(client.routes[route], data=circuit.form.html)
    ext = '.zip'
    if not hasattr(circuit.form, 'generate_diagram'):
        ext = '.txt'
        # Allow minor differences in configs due to VLAN/pw-id RNG
        min_accuracy = 0.985
        result_accuracy = SequenceMatcher(None, response.data.decode(), circuit.configs).ratio()
        assert result_accuracy >= min_accuracy

    # Verify file is sent
    file = circuit.filename + ext
    assert len(response.data) > 0
    assert response.headers['Content-Disposition'] == f"attachment; filename=\"{file}\""

    # Clean up zip files
    # try:
    #     os.unlink(os.path.join(SERVED_FILES_DIR, file))
    # except FileNotFoundError:
    #     pass
    # else:
    #     assert os.path.exists(os.path.join(SERVED_FILES_DIR, file)) is False


# def test_login(client):
#     response = client.post(client.routes['login'], data={'username': 'user', 'password': 'pass'})
#     assert b'Invalid credentials' in response.data


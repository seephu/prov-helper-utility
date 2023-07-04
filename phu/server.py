# Standard Library
import json
import os
import sys
import time
import traceback
import webbrowser

# Third party
import webview
import dotenv
from flask import Flask, render_template, jsonify, request, redirect, send_file, flash, url_for, \
    session, make_response
from werkzeug.exceptions import HTTPException
from loguru import logger

# Custom
import app
import database
import ssh
from configgen import ConfigGen, VarsFile
from decomgen import DecomGen
from ipvalidator import IPValidator
from oh_diagramgen import OntarioHealthSrx

from flaskwebgui import FlaskUI

UPLOAD_DIR = app.resource_path('../assets/upload')
SERVED_FILES_DIR = app.resource_path('../assets/served_files')
GUI_DIR = app.resource_path('../gui')
TEMPLATES_DIR = os.path.join(GUI_DIR, 'templates')
COMMERCIAL_DB = database.COMMERCIAL_DB
OH_DB = database.OH_DB

dotenv.load_dotenv()
server = Flask(__name__, static_folder=GUI_DIR, template_folder=TEMPLATES_DIR)
server.config.from_prefixed_env()
server.config['UPLOAD_FOLDER'] = UPLOAD_DIR
server.config['TESTING'] = True


def setup_session():
    """Sets up user session"""
    session.permanent = True
    if session.get('credentials') is None:
        session['credentials'] = ssh.Credentials('Username', 'Password')

@server.context_processor
def inject_dropdowns():
    """Inject commonly used dropdowns/variables into all templates"""
    dropdowns = {
        'version': os.getenv('VERSION'),
        'asr9k_routers': COMMERCIAL_DB.get_all('asr9k_routers'),
        'interface_speeds': COMMERCIAL_DB.interface_speeds,
        'raisecom_db': COMMERCIAL_DB.raisecoms
    }
    return dropdowns


@server.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-cache'
    return response


@server.route('/')
def landing():
    """Render index.html. Initialization is performed asynchronously in initialize() function"""
    setup_session()

    try:
        import pyi_splash
        pyi_splash.close()
    except:
        pass
    return render_template('index.html', version=os.getenv('VERSION'))


@server.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        form = request.form.to_dict()
        credentials = ssh.Credentials(form['username'], form['password'])

        if credentials.verify():
            credentials.save()
            session['credentials'] = credentials
            flash(f"Successfully logged in as {credentials.username}")
            return redirect(url_for('landing'))
        else:
            error = 'Invalid credentials'
    return render_template('login.html', error=error)


@server.route('/oh/configgen/<circuit_type>', methods=['GET', 'POST'])
def oh_configgen(circuit_type):
    # change site_type to circuit_type to prevent confusion
    if request.method == 'POST':
        if request.form.get('formType') == 'varsFile':
            try:
                logger.info('Generating configs from vars file..')
                form = VarsFile().load(request.files['varsFile'])
            except KeyError:
                logger.warning('Error parsing vars file.. trying to parse it as a legacy keys file.')
                form = VarsFile().load_legacy(request.files['varsFile'])
        else:
            logger.debug('Generating configs from form fields..')
            form = request.form.to_dict()

        site = ConfigGen().generator(form)
        configs = site.generate_files()
        return send_file(configs, as_attachment=True)

    return render_template(f'ontario_health/configgen_{circuit_type}.html', OH_DB=OH_DB)


@server.route('/oh/diagram-gen', methods=['GET', 'POST'])
def oh_diagram_gen():
    if request.method == 'POST':
        key_file = request.files['key_file']
        diagram_gen = OntarioHealthSrx(request.form.to_dict(), key_file)
        out_file = os.path.join(SERVED_FILES_DIR, diagram_gen.filename)
        diagram_gen.generate(out_file)
        return send_file(out_file, as_attachment=True)

    return render_template('ontario_health/diagramgen.html')


@server.route('/oh/decomgen', methods=['GET', 'POST'])
def oh_decomgen():
    pe_routers = OH_DB.get_all('pe_sites')
    return render_template('ontario_health/decomgen.html', pe_routers=pe_routers)


@server.route('/oh/ip-validator', methods=['GET', 'POST'])
def oh_ip_validator():
    if request.method == 'POST':
        core_router = request.form['core_router']

        # Save temporary diagram
        file = request.files['diagram']
        temp_diagram = os.path.join(server.config['UPLOAD_FOLDER'], 'Diagram.vsd')
        file.save(temp_diagram)

        # Validate IP's and clean-up diagram
        ip_validator = IPValidator(temp_diagram, core_router)
        ip_validator.validate()
        app.remove_file(temp_diagram)

        return render_template('ontario_health/ip_validator_results.html', ip_validator=ip_validator)

    else:
        allowed_core_routers = ['TOROONXNPED12', 'TOROONXNPED13', 'EBCKONCBPED10', 'EBCKONCBPED11', 'PED30']
        return render_template('ontario_health/ip_validator.html', allowed_core_routers=allowed_core_routers)


@server.route('/commercial/configgen/<circuit_type>', methods=['GET', 'POST'])
def commercial_configgen(circuit_type):
    if request.method == 'POST':
        form = request.form.to_dict()
        form.update({'circuitType': circuit_type})
        circuit = ConfigGen().generator(form)
        if form.get('generateDiagram'):
            ext = '.zip'
            file = os.path.join(SERVED_FILES_DIR, circuit.filename + ext)
            circuit.zip(file)
        else:
            ext = '.txt'
            file = app.make_temp(circuit.configs.encode())
        return send_file(file, as_attachment=True, download_name=circuit.filename + ext)

    return render_template(f'commercial/configgen_{circuit_type}.html')


@server.route('/commercial/decomgen', methods=['GET', 'POST'])
def commercial_decomgen():
    return render_template('commercial/decomgen.html')


@server.route('/generate/decom', methods=['POST'])
def generate_decom():
    # Pass form to DecomGen factory
    form = request.form.to_dict()
    circuit = DecomGen().generator(form)
    if form['circuitType'] != 'autodetect':
        circuit.fetch_rollbacks()

    try:
        configs = app.make_temp(circuit.configs.encode())
    except AttributeError:
        logger.error('Error during rollback gathering, unable to generate configs')
        return 'Error', 500
    # Create response for front-end fetch API
    fname = circuit.filename
    resp = make_response(send_file(configs, as_attachment=True, download_name=fname))
    resp.headers['fname'] = fname
    return resp


@server.route('/get-pw-id', methods=['GET', 'POST'])
def get_pw_id():
    """Returns a string of the next available pseudowire ID between 2 routers"""
    form = request.form.to_dict()
    if form['routerA'] == 'null' or form['routerZ'] == 'null':
        logger.error(f"Ensure both router fields are filled out to fetch a pseudowire ID")
        return

    logger.debug('Fetching available pseudowire ID between: {}', form)
    device = ssh.Device(form['routerA'])
    with device.connect():
        pw_id = device.fetch_next_pw_id(form['routerZ'])

    if pw_id is not None:
        logger.success('Next available pseudowire: {}', pw_id)
        return make_response(jsonify(pw_id), 200)
    logger.error('Error fetching pseudowire ID')


@server.route('/verify-vpn-id', methods=['GET', 'POST'])
def verify_vpn_id():
    vpn_id = request.get_json()
    logger.debug('Verifying VPN-ID: {}', vpn_id)
    if not int(vpn_id):
        logger.error('{} is not a valid numeric VPN ID', vpn_id)
        return

    available = False
    result = ssh.discover_legs(vpn_id)
    if result is None:
        available = True
    return make_response(jsonify(int(available)), 200)


@server.route('/coin-path-names')
def coin_path_names():
    return render_template('commercial/coin.html')


@server.route('/database/<db>', methods=['GET', 'POST'])
def db_viewer(db):
    db_map = {
        'commercial': COMMERCIAL_DB,
        'ontario_health': OH_DB
    }
    selected_db = db_map[db]

    if request.method == 'POST':
        sheet = request.form.to_dict()['sheet']
        if not sheet:
            return 'No sheet selected', 200
        table = {'headers': selected_db.headers(sheet), 'rows': selected_db.data(sheet)}
        return make_response(jsonify(table))
    return render_template('database.html', sheets=selected_db.sheet_names)


@server.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404


@server.errorhandler(Exception)
def handle_exception(e):
    # pass through HTTP errors
    if isinstance(e, HTTPException):
        return e

    # Handle non-HTTP exceptions
    logger.opt(exception=True).debug('')
    return render_template('500.html', e=traceback.format_exc()), 500


@server.route('/init', methods=['POST'])
def initialize():
    """
    Perform heavy-lifting initialization asynchronously.
    :return:
    """
    can_start = app.initialize()

    if can_start:
        response = {
            'status': 'ok',
        }
    else:
        response = {
            'status': 'error'
        }

    return jsonify(response)


@server.route('/fullscreen', methods=['POST'])
def fullscreen():
    webview.windows[0].toggle_fullscreen()
    return jsonify({})


@server.route('/open-url', methods=['POST'])
def open_url():
    url = request.json['url']
    webbrowser.open_new_tab(url)

    return jsonify({})


@server.route('/do/stuff', methods=['POST'])
def do_stuff():
    result = app.do_stuff()

    if result:
        response = {'status': 'ok', 'result': result}
    else:
        response = {'status': 'error'}

    return jsonify(response)


if __name__ == '__main__':
    pass

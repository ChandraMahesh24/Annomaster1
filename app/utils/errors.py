from flask import jsonify

def bad_request(msg):
    return jsonify({'error': msg}), 400

def not_found(msg='Not found'):
    return jsonify({'error': msg}), 404

def forbidden(msg='Forbidden'):
    return jsonify({'error': msg}), 403

def conflict(msg):
    return jsonify({'error': msg}), 409

def server_error(msg='Internal server error'):
    return jsonify({'error': msg}), 500

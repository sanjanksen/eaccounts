import os
from flask import Flask, jsonify, request
from scraper import DiningBalanceScraper

app = Flask(__name__)


@app.route('/api/balance', methods=['GET'])
def get_balance():
    scraper = DiningBalanceScraper()
    result = scraper.get_balance()

    if result.get('error') == 'session_expired':
        return jsonify({'error': 'Session expired — cookies need to be refreshed'}), 401

    if 'error' in result:
        return jsonify(result), 500

    return jsonify(result)


@app.route('/api/transactions', methods=['GET'])
def get_transactions():
    begin_date = request.args.get('begin_date')  # e.g. 2/1/2026 12:00 AM
    end_date = request.args.get('end_date')

    scraper = DiningBalanceScraper()
    result = scraper.get_transactions(begin_date=begin_date, end_date=end_date)

    if result.get('error') == 'session_expired':
        return jsonify({'error': 'Session expired — cookies need to be refreshed'}), 401

    if 'error' in result:
        return jsonify(result), 500

    return jsonify(result)


@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

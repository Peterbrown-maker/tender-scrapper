from flask import Flask, jsonify, send_file, request
from flask_cors import CORS
import os
import sys
import pandas as pd
from tenders import TenderScraper
import tempfile
import datetime
import base64

app = Flask(__name__)

# Configure CORS to allow all origins for simplicity
CORS(app, resources={
    r"/api/*": {
        "origins": "*",  # Allow all origins
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"],
        "supports_credentials": False  # Change to False for no-cors mode
    }
})

@app.route('/api/scrape-tenders', methods=['POST', 'OPTIONS'])
def scrape_tenders():
    # Handle preflight requests
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
        
    try:
        scraper = TenderScraper()
        tenders = scraper.scrape_tenders()
        
        if tenders:
            # Use temp directory in cloud environment
            temp_dir = tempfile.mkdtemp()
            
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            excel_filename = os.path.join(temp_dir, f'tenders_{timestamp}.xlsx')
            
            df = pd.DataFrame(tenders)
            
            all_columns = [
                'Title', 'URL', 'New', 'Tender Type', 'Bid Number', 'Department',
                'Bid Description', 'Place where goods, works or services are required',
                'Opening Date', 'Closing Date', 'Modified Date', 'Date Published',
                'Enquiries/Contact Person', 'Email', 'Tel',
                'Briefing Session', 'Compulsory Briefing', 'Briefing Date',
                'Venue', 'Special Conditions', 'Description'
            ]
            
            for col in all_columns:
                if col not in df.columns:
                    df[col] = ''
            
            df = df[all_columns]
            df.to_excel(excel_filename, index=False)
            
            # Store file in Google Cloud Storage (recommended) or return base64
            # Here we'll return the Excel as base64 for simplicity
            with open(excel_filename, 'rb') as f:
                excel_data = base64.b64encode(f.read()).decode()
                
            # Clean up temp files
            os.remove(excel_filename)
            os.rmdir(temp_dir)
            
            return jsonify({
                'tenders': tenders[:50],
                'excelData': excel_data,  # Base64 encoded Excel file
                'excelFileName': f'tenders_{timestamp}.xlsx'
            })
        else:
            return jsonify({
                'tenders': [],
                'message': 'No new tenders found'
            }), 404
    
    except Exception as e:
        return jsonify({
            'error': str(e)
        }), 500

# Add a test endpoint
@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'healthy'}), 200

# Entry point for Google Cloud Functions
def main(request):
    # Important: Create app context for Cloud Functions
    with app.app_context():
        return app.full_dispatch_request()

# For local development
if __name__ == '__main__':
    app.run(debug=True, port=5000, host='0.0.0.0')
from flask import Flask, jsonify, request
from flask_cors import CORS
import os
import sys
import pandas as pd
import tempfile
import datetime
import gc  # For garbage collection
import base64
import logging
import traceback

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import TenderScraper with memory limit
from tenders import TenderScraper  # We'll optimize this class separately

app = Flask(__name__)
CORS(app, origins=['http://localhost:3000', 'https://tenderscapper.web.app'])

@app.route('/api/health', methods=['GET'])
def health_check():
    """Simple endpoint to check if the server is running."""
    return jsonify({"status": "healthy"})

@app.route('/api/scrape-tenders', methods=['POST'])
def scrape_tenders():
    """Endpoint to scrape tender data with memory optimization."""
    try:
        logger.info("Starting tender scraping operation")
        
        # Get parameters from request (you could add pagination, etc.)
        max_pages = request.json.get('max_pages', 3)  # Default to 3 pages to limit memory
        
        # Create scraper with memory optimizations
        scraper = TenderScraper(max_pages=max_pages)
        
        # Scrape tenders with limits
        tenders = scraper.scrape_tenders()
        
        # Force garbage collection to free memory
        gc.collect()
        
        if tenders:
            logger.info(f"Found {len(tenders)} tenders")
            
            # Use temp directory
            temp_dir = tempfile.mkdtemp()
            
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            excel_filename = os.path.join(temp_dir, f'tenders_{timestamp}.xlsx')
            
            # Select only essential columns to reduce memory
            essential_columns = [
                'Title', 'URL', 'Bid Number', 'Department',
                'Bid Description', 'Closing Date', 'Email', 'Tel'
            ]
            
            # Create a new DataFrame with only essential data for the response
            response_data = []
            for t in tenders:
                item = {col: t.get(col, '') for col in essential_columns}
                response_data.append(item)
            
            # Create DataFrame for Excel with all data
            df = pd.DataFrame(tenders)
            
            # Normalize columns to ensure consistent output
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
            
            # Only keep needed columns
            df = df[all_columns]
            
            # Write to Excel with optimized settings
            df.to_excel(excel_filename, index=False, engine='openpyxl')
            
            # Free memory
            del df
            gc.collect()
            
            # Return the Excel as base64
            with open(excel_filename, 'rb') as f:
                excel_data = base64.b64encode(f.read()).decode()
            
            # Remove temp file
            os.remove(excel_filename)
            os.rmdir(temp_dir)
            
            return jsonify({
                'tenders': response_data[:50],  # Limit to 50 for the response
                'excelData': excel_data,
                'excelFileName': f'tenders_{timestamp}.xlsx'
            })
        else:
            logger.info("No new tenders found")
            return jsonify({
                'tenders': [],
                'message': 'No new tenders found'
            }), 404
    
    except Exception as e:
        logger.error(f"Error in scrape_tenders: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({
            'error': str(e)
        }), 500

# Entry point for Google Cloud Functions
def main(request):
    with app.app_context():
        return app.full_dispatch_request()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
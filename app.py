from flask import Flask, request, jsonify
import os
import tempfile
import uuid
from datetime import datetime

app = Flask(__name__)

# Simple in-memory storage
results_store = {}

@app.route('/')
def home():
    """Simple HTML page"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>PDF Table Extractor</title>
        <style>
            body { font-family: Arial, sans-serif; max-width: 800px; margin: 50px auto; padding: 20px; }
            .form-group { margin: 20px 0; }
            input, button { width: 100%; padding: 10px; margin: 5px 0; border: 1px solid #ddd; border-radius: 5px; }
            button { background: #007bff; color: white; border: none; cursor: pointer; }
            button:hover { background: #0056b3; }
            .hidden { display: none; }
            .alert { padding: 15px; margin: 10px 0; border-radius: 5px; }
            .alert-success { background: #d4edda; color: #155724; }
            .alert-error { background: #f8d7da; color: #721c24; }
        </style>
    </head>
    <body>
        <h1>📊 PDF Table Extractor</h1>
        
        <form id="uploadForm">
            <div class="form-group">
                <label>Google AI API Key:</label>
                <input type="password" id="apiKey" placeholder="Enter your Google AI API key" required>
                <small>Get from <a href="https://makersuite.google.com/app/apikey" target="_blank">Google AI Studio</a></small>
            </div>
            
            <div class="form-group">
                <label>PDF File:</label>
                <input type="file" id="pdfFile" accept=".pdf" required>
            </div>
            
            <button type="submit" id="submitBtn">Extract Tables</button>
        </form>
        
        <div id="loading" class="hidden">
            <p>⏳ Processing PDF... Please wait...</p>
        </div>
        
        <div id="message"></div>
        <div id="results"></div>
        
        <script>
            document.getElementById('uploadForm').addEventListener('submit', async function(e) {
                e.preventDefault();
                
                const apiKey = document.getElementById('apiKey').value;
                const pdfFile = document.getElementById('pdfFile').files[0];
                const loading = document.getElementById('loading');
                const message = document.getElementById('message');
                const results = document.getElementById('results');
                const submitBtn = document.getElementById('submitBtn');
                
                // Reset
                message.innerHTML = '';
                results.innerHTML = '';
                loading.classList.remove('hidden');
                submitBtn.disabled = true;
                
                try {
                    // Create form data
                    const formData = new FormData();
                    formData.append('api_key', apiKey);
                    formData.append('file', pdfFile);
                    
                    // Send request
                    const response = await fetch('/upload', {
                        method: 'POST',
                        body: formData
                    });
                    
                    const text = await response.text();
                    console.log('Response:', text);
                    
                    if (!text.trim()) {
                        throw new Error('Server returned empty response');
                    }
                    
                    const data = JSON.parse(text);
                    
                    if (data.success) {
                        message.innerHTML = '<div class="alert alert-success">✅ Success! PDF processed.</div>';
                        results.innerHTML = `
                            <h3>Results:</h3>
                            <p><strong>File:</strong> ${data.results.pdf_name}</p>
                            <p><strong>Pages:</strong> ${data.results.total_pages}</p>
                            <p><strong>Tables Found:</strong> ${data.results.total_tables_extracted}</p>
                            ${data.results.csv_files.map(file => 
                                `<p><a href="/download_csv/${data.extraction_id}/${file}">📄 Download ${file}</a></p>`
                            ).join('')}
                            <p><a href="/download/${data.extraction_id}">📦 Download All (ZIP)</a></p>
                        `;
                    } else {
                        message.innerHTML = `<div class="alert alert-error">❌ Error: ${data.error}</div>`;
                    }
                } catch (err) {
                    console.error('Error:', err);
                    message.innerHTML = `<div class="alert alert-error">❌ Error: ${err.message}</div>`;
                } finally {
                    loading.classList.add('hidden');
                    submitBtn.disabled = false;
                }
            });
        </script>
    </body>
    </html>
    """

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'message': 'Server running'})

@app.route('/upload', methods=['POST'])
def upload():
    """Handle file upload with maximum error protection"""
    try:
        print("=== UPLOAD STARTED ===")
        
        # Check request
        if not request.files:
            return jsonify({'error': 'No files in request'}), 400
            
        if 'file' not in request.files:
            return jsonify({'error': 'No file field'}), 400
            
        file = request.files['file']
        api_key = request.form.get('api_key', '').strip()
        
        print(f"File: {file.filename}")
        print(f"API key length: {len(api_key)}")
        
        # Validate inputs
        if not file or not file.filename:
            return jsonify({'error': 'No file selected'}), 400
            
        if not api_key:
            return jsonify({'error': 'API key required'}), 400
            
        if not file.filename.lower().endswith('.pdf'):
            return jsonify({'error': 'Must be PDF file'}), 400
        
        # Test imports safely
        print("Testing imports...")
        try:
            import google.generativeai as genai
            print("✓ google.generativeai imported")
        except ImportError as e:
            print(f"Import error: {e}")
            return jsonify({'error': 'google-generativeai not installed'}), 500
            
        try:
            import PyMuPDF as fitz
            print("✓ PyMuPDF imported")
        except ImportError as e:
            print(f"Import error: {e}")
            return jsonify({'error': 'PyMuPDF not installed'}), 500
            
        try:
            import pandas as pd
            print("✓ pandas imported")
        except ImportError as e:
            print(f"Import error: {e}")
            return jsonify({'error': 'pandas not installed'}), 500
        
        # Test API key
        print("Testing API key...")
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-2.0-flash-exp')
            # Quick test
            test_response = model.generate_content("Hello")
            print("✓ API key works")
        except Exception as e:
            print(f"API error: {e}")
            return jsonify({'error': f'Invalid API key: {str(e)}'}), 400
        
        # Save file safely
        print("Saving file...")
        extraction_id = str(uuid.uuid4())
        
        # Create temp directory
        temp_dir = tempfile.mkdtemp()
        file_path = os.path.join(temp_dir, f"upload_{extraction_id}.pdf")
        
        try:
            file.save(file_path)
            file_size = os.path.getsize(file_path)
            print(f"✓ File saved: {file_size} bytes")
        except Exception as e:
            return jsonify({'error': f'File save failed: {str(e)}'}), 500
        
        # Process PDF (simplified)
        print("Processing PDF...")
        try:
            # Open PDF
            doc = fitz.open(file_path)
            total_pages = len(doc)
            print(f"✓ PDF opened: {total_pages} pages")
            
            # Simple table extraction
            tables_found = 0
            csv_files = []
            
            for page_num in range(min(total_pages, 5)):  # Limit to 5 pages for safety
                page = doc[page_num]
                tables = page.find_tables()
                
                for i, table in enumerate(tables):
                    try:
                        df = table.to_pandas()
                        if not df.empty:
                            csv_filename = f"table_page{page_num+1}_{i+1}.csv"
                            csv_path = os.path.join(temp_dir, csv_filename)
                            df.to_csv(csv_path, index=False)
                            csv_files.append(csv_path)
                            tables_found += 1
                            print(f"✓ Table {i+1} extracted from page {page_num+1}")
                    except Exception as e:
                        print(f"Table extraction error: {e}")
                        continue
            
            doc.close()
            
            # Store results
            results = {
                'pdf_name': file.filename,
                'total_pages': total_pages,
                'pages_with_tables': len([p for p in range(total_pages) if len(doc[p].find_tables()) > 0]) if total_pages <= 5 else "Unknown",
                'total_tables_extracted': tables_found,
                'csv_files': csv_files,
                'temp_dir': temp_dir
            }
            
            results_store[extraction_id] = results
            
            print(f"✓ Processing complete: {tables_found} tables")
            
            return jsonify({
                'success': True,
                'extraction_id': extraction_id,
                'results': {
                    'pdf_name': results['pdf_name'],
                    'total_pages': results['total_pages'],
                    'pages_with_tables': results['pages_with_tables'],
                    'total_tables_extracted': results['total_tables_extracted'],
                    'csv_files': [os.path.basename(f) for f in csv_files]
                }
            })
            
        except Exception as e:
            print(f"Processing error: {e}")
            return jsonify({'error': f'PDF processing failed: {str(e)}'}), 500
        
    except Exception as e:
        print(f"General error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Server error: {str(e)}'}), 500

@app.route('/download/<extraction_id>')
def download_zip(extraction_id):
    """Download all CSV files as ZIP"""
    try:
        if extraction_id not in results_store:
            return jsonify({'error': 'Results not found'}), 404
        
        results = results_store[extraction_id]
        
        if not results['csv_files']:
            return jsonify({'error': 'No CSV files'}), 404
        
        import zipfile
        from flask import send_file
        
        zip_path = os.path.join(results['temp_dir'], 'tables.zip')
        
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            for csv_file in results['csv_files']:
                if os.path.exists(csv_file):
                    zipf.write(csv_file, os.path.basename(csv_file))
        
        return send_file(zip_path, as_attachment=True, download_name='extracted_tables.zip')
        
    except Exception as e:
        return jsonify({'error': f'Download error: {str(e)}'}), 500

@app.route('/download_csv/<extraction_id>/<filename>')
def download_csv(extraction_id, filename):
    """Download single CSV file"""
    try:
        if extraction_id not in results_store:
            return jsonify({'error': 'Results not found'}), 404
        
        results = results_store[extraction_id]
        
        for csv_file in results['csv_files']:
            if os.path.basename(csv_file) == filename:
                if os.path.exists(csv_file):
                    from flask import send_file
                    return send_file(csv_file, as_attachment=True, download_name=filename)
        
        return jsonify({'error': 'File not found'}), 404
        
    except Exception as e:
        return jsonify({'error': f'Download error: {str(e)}'}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"🚀 Starting server on port {port}")
    app.run(debug=False, host='0.0.0.0', port=port)

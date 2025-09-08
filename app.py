from http.server import HTTPServer, BaseHTTPRequestHandler
import json

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health/':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            response = json.dumps({"status": "OK"})
            self.wfile.write(response.encode())
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'Not Found')

def run_server():
    server_address = ('', 8000)
    httpd = HTTPServer(server_address, HealthHandler)
    print('Server running on port 8000...')
    httpd.serve_forever()

if __name__ == '__main__':
    run_server()
import os
from fpdf import FPDF
from PIL import Image

class LabFlowPDF(FPDF):
    def header(self):
        # We'll handle headers manually per page for better design control
        pass

    def footer(self):
        self.set_y(-15)
        self.set_font("helvetica", "I", 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f"LabFlow - Modern LIS Solution | Page {self.page_no()}", align="C")

def create_pdf():
    pdf = LabFlowPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    
    # Define Colors
    PRIMARY_BLUE = (37, 99, 235)
    DARK_BLUE = (30, 58, 138)
    TEXT_COLOR = (31, 41, 55)
    SUB_TEXT = (75, 85, 99)
    WHITE = (255, 255, 255)
    
    # Image Paths
    img_hero = "temp-images/Gemini_Generated_Image_g7lsjug7lsjug7ls.png"
    img_dash = "temp-images/Screenshot 2026-02-14 000213.png"
    img_admin = "temp-images/Screenshot 2026-02-14 000243.png"

    # --- PAGE 1: HERO ---
    pdf.add_page()
    
    # Background Accent
    pdf.set_fill_color(*PRIMARY_BLUE)
    pdf.rect(0, 0, 210, 80, 'F')
    
    pdf.set_y(30)
    pdf.set_font("helvetica", "B", 34)
    pdf.set_text_color(*WHITE)
    pdf.cell(0, 15, "LabFlow", align="C", ln=True)
    
    pdf.set_font("helvetica", "", 16)
    pdf.cell(0, 10, "Next-Gen Laboratory Management System", align="C", ln=True)
    
    # Hero Image
    if os.path.exists(img_hero):
        # Center the image
        pdf.image(img_hero, x=15, y=90, w=180)
    
    pdf.set_y(190)
    pdf.set_font("helvetica", "B", 20)
    pdf.set_text_color(*DARK_BLUE)
    pdf.multi_cell(0, 10, "Empowering Diagnostics with Precision & Speed", align="C")
    
    pdf.ln(5)
    pdf.set_font("helvetica", "", 12)
    pdf.set_text_color(*SUB_TEXT)
    pdf.multi_cell(0, 7, "A minimalist, high-performance solution for pathology laboratories. Built for scalability, security, and seamless user experience.", align="C")

    # --- PAGE 2: DASHBOARD & FEATURES ---
    pdf.add_page()
    
    pdf.set_y(20)
    pdf.set_font("helvetica", "B", 24)
    pdf.set_text_color(*PRIMARY_BLUE)
    pdf.cell(0, 15, "Intuitive Workspace", align="L", ln=True)
    
    pdf.set_font("helvetica", "", 12)
    pdf.set_text_color(*SUB_TEXT)
    pdf.multi_cell(0, 7, "LabFlow's core dashboard provides a comprehensive overview of your daily operations. Monitor patient throughput, test completion rates, and pending reports in real-time.")
    
    pdf.ln(10)
    if os.path.exists(img_dash):
        # Add a border to the screenshot
        pdf.set_draw_color(229, 231, 235)
        pdf.image(img_dash, x=10, y=60, w=190)
        # pdf.rect(10, 60, 190, 100) # Optional border if needed

    pdf.set_y(180)
    pdf.set_font("helvetica", "B", 16)
    pdf.set_text_color(*DARK_BLUE)
    pdf.cell(0, 10, "Core Capabilities:", ln=True)
    
    pdf.set_font("helvetica", "", 11)
    features = [
        "- One-Click Patient Registration",
        "- Real-time Test Progress Tracking",
        "- Secure Cloud-Based Data Management",
        "- Instant PDF Report Generation"
    ]
    for feat in features:
        pdf.set_x(15)
        pdf.cell(0, 7, feat, ln=True)

    # --- PAGE 3: ADMIN & CONCLUSION ---
    pdf.add_page()
    
    pdf.set_y(20)
    pdf.set_font("helvetica", "B", 24)
    pdf.set_text_color(*PRIMARY_BLUE)
    pdf.cell(0, 15, "Advanced Administration", align="L", ln=True)
    
    pdf.set_font("helvetica", "", 12)
    pdf.set_text_color(*SUB_TEXT)
    pdf.multi_cell(0, 7, "Maintain full control with our robust Admin Console. Track system health, monitor performance, and review detailed activity logs to ensure clinical excellence.")
    
    pdf.ln(10)
    if os.path.exists(img_admin):
        pdf.image(img_admin, x=10, y=60, w=190)
        
    pdf.set_y(190)
    pdf.set_font("helvetica", "B", 18)
    pdf.set_text_color(*PRIMARY_BLUE)
    pdf.cell(0, 15, "Ready for the Future", align="C", ln=True)
    
    pdf.set_font("helvetica", "I", 12)
    pdf.set_text_color(*SUB_TEXT)
    pdf.multi_cell(0, 7, "LabFlow combines medical-grade reliability with modern software aesthetics. Designed to grow with your laboratory's needs.", align="C")
    
    # CTA Box
    pdf.ln(10)
    pdf.set_fill_color(243, 244, 246)
    pdf.set_draw_color(*PRIMARY_BLUE)
    pdf.rect(15, 240, 180, 25, 'FD')
    
    pdf.set_y(245)
    pdf.set_font("helvetica", "B", 14)
    pdf.set_text_color(*PRIMARY_BLUE)
    pdf.cell(0, 8, "Contact for Implementation & Customization", align="C", ln=True)
    pdf.set_font("helvetica", "", 10)
    pdf.set_text_color(*SUB_TEXT)
    pdf.cell(0, 5, "Available on Fiverr @rehan_ahmed_dev ", align="C", ln=True)

    # Output
    output_path = "LabFlow_Presentation.pdf"
    pdf.output(output_path)
    print(f"PDF successfully generated at: {output_path}")

if __name__ == "__main__":
    create_pdf()

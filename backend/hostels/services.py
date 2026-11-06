from django.conf import settings
from django.core.mail import EmailMultiAlternatives


def send_registration_email(resident):
    """Send a registration confirmation email to the hostel owner.

    The resident registration must remain persisted even if email delivery fails.
    """
    try:
        hostel = resident.hostel
        owner_email = getattr(hostel.owner, 'email', None)
        if not owner_email:
            return False

        subject = f"Resident registration submitted for {hostel.hostel_name}"
        registration_status = resident.status or 'PENDING'
        context = {
            'hostel_name': hostel.hostel_name,
            'resident_name': resident.full_name,
            'mobile_number': resident.mobile_number,
            'joining_date': resident.joining_date,
            'registration_date': resident.created_at.date() if hasattr(resident.created_at, 'date') else resident.created_at,
            'registration_status': registration_status,
        }

        text_body = (
            f"Hostel: {context['hostel_name']}\n"
            f"Resident: {context['resident_name']}\n"
            f"Mobile number: {context['mobile_number']}\n"
            f"Joining date: {context['joining_date']}\n"
            f"Registration date: {context['registration_date']}\n"
            f"Registration status: {context['registration_status']}"
        )
        html_body = f"""
            <html>
              <body style="font-family: Arial, sans-serif; color: #111827; line-height: 1.6;">
                <div style="max-width: 600px; margin: 0 auto; padding: 24px; border: 1px solid #e5e7eb; border-radius: 12px;">
                  <h2 style="margin-bottom: 16px; color: #111827;">Resident registration submitted</h2>
                  <p style="margin: 8px 0;">A new resident registration has been received for <strong>{context['hostel_name']}</strong>.</p>
                  <table style="width: 100%; border-collapse: collapse; margin-top: 16px;">
                    <tr><td style="padding: 8px 0; font-weight: 600; width: 180px;">Hostel</td><td>{context['hostel_name']}</td></tr>
                    <tr><td style="padding: 8px 0; font-weight: 600;">Resident name</td><td>{context['resident_name']}</td></tr>
                    <tr><td style="padding: 8px 0; font-weight: 600;">Mobile number</td><td>{context['mobile_number']}</td></tr>
                    <tr><td style="padding: 8px 0; font-weight: 600;">Joining date</td><td>{context['joining_date']}</td></tr>
                    <tr><td style="padding: 8px 0; font-weight: 600;">Registration date</td><td>{context['registration_date']}</td></tr>
                    <tr><td style="padding: 8px 0; font-weight: 600;">Registration status</td><td>{context['registration_status']}</td></tr>
                  </table>
                </div>
              </body>
            </html>
        """

        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@localhost') or 'noreply@localhost'
        email = EmailMultiAlternatives(subject, text_body, from_email, [owner_email])
        email.attach_alternative(html_body, 'text/html')
        email.send(fail_silently=False)
        return True
    except Exception:
        return False
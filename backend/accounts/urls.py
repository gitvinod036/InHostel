from django.urls import path

from .views import (
    ForgotPasswordView,
    GoogleAuthView,
    OTPRequestView,
    OTPVerifyView,
    OwnerLoginView,
    OwnerLogoutView,
    OwnerProfileView,
    OwnerRefreshView,
    OwnerRegisterView,
    ResetPasswordView,
)

urlpatterns = [
    path('register/', OwnerRegisterView.as_view(), name='owner-register'),
    path('login/', OwnerLoginView.as_view(), name='owner-login'),
    path('refresh/', OwnerRefreshView.as_view(), name='owner-refresh'),
    path('logout/', OwnerLogoutView.as_view(), name='owner-logout'),
    path('forgot-password/', ForgotPasswordView.as_view(), name='owner-forgot-password'),
    path('reset-password/', ResetPasswordView.as_view(), name='owner-reset-password'),
    path('otp/request/', OTPRequestView.as_view(), name='owner-otp-request'),
    path('otp/verify/', OTPVerifyView.as_view(), name='owner-otp-verify'),
    path('google/', GoogleAuthView.as_view(), name='owner-google-auth'),
    path('me/', OwnerProfileView.as_view(), name='owner-profile'),
]

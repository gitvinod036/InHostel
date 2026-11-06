from django.conf import settings
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import Owner
from .serializers import (
    ForgotPasswordSerializer,
    GoogleAuthSerializer,
    OTPRequestSerializer,
    OTPVerifySerializer,
    OwnerLoginSerializer,
    OwnerLogoutSerializer,
    OwnerPublicSerializer,
    OwnerRegisterSerializer,
    ResetPasswordSerializer,
)
from .services import create_owner_otp, create_password_reset_token


class OwnerRegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = OwnerRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        owner = serializer.save()
        refresh = RefreshToken.for_user(owner)
        return Response(
            {
                'message': 'Owner account created successfully.',
                'owner': OwnerPublicSerializer(owner).data,
                'access': str(refresh.access_token),
                'refresh': str(refresh),
            },
            status=status.HTTP_201_CREATED,
        )


class OwnerLoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = OwnerLoginSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        owner = serializer.validated_data['user']
        refresh = RefreshToken.for_user(owner)
        return Response(
            {
                'message': 'Authentication successful.',
                'owner': OwnerPublicSerializer(owner).data,
                'access': str(refresh.access_token),
                'refresh': str(refresh),
            },
            status=status.HTTP_200_OK,
        )


class OwnerRefreshView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        refresh_token = request.data.get('refresh')
        if not refresh_token:
            return Response({'detail': 'Refresh token is required.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            refresh = RefreshToken(refresh_token)
            return Response({'access': str(refresh.access_token)}, status=status.HTTP_200_OK)
        except Exception:
            return Response({'detail': 'Refresh token is invalid or expired.'}, status=status.HTTP_401_UNAUTHORIZED)


class OwnerLogoutView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = OwnerLogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response({'message': 'Logged out successfully.'}, status=status.HTTP_200_OK)


class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']
        owner = Owner.objects.filter(email__iexact=email).first()
        if owner:
            token = create_password_reset_token(owner)
            if settings.DEBUG:
                return Response({'message': 'If an owner exists, a password reset link is being prepared.', 'reset_token': token}, status=status.HTTP_200_OK)
        return Response({'message': 'If an owner exists, a password reset link is being prepared.'}, status=status.HTTP_200_OK)


class ResetPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({'message': 'Password reset successfully.'}, status=status.HTTP_200_OK)


class OTPRequestView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = OTPRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        mobile_number = serializer.validated_data['mobile_number']
        owner = Owner.objects.filter(mobile_number=mobile_number).first()
        if owner:
            otp_record, otp_code = create_owner_otp(owner, mobile_number)
            if settings.DEBUG:
                return Response({'message': 'OTP sent successfully.', 'otp_debug_code': otp_code}, status=status.HTTP_200_OK)
        return Response({'message': 'If the mobile number matches an owner account, an OTP has been sent.'}, status=status.HTTP_200_OK)


class OTPVerifyView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = OTPVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        owner = serializer.validated_data['owner']
        refresh = RefreshToken.for_user(owner)
        return Response(
            {
                'message': 'OTP verification successful.',
                'owner': OwnerPublicSerializer(owner).data,
                'access': str(refresh.access_token),
                'refresh': str(refresh),
            },
            status=status.HTTP_200_OK,
        )


class GoogleAuthView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = GoogleAuthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        owner = serializer.validated_data['owner']
        refresh = RefreshToken.for_user(owner)
        return Response(
            {
                'message': 'Google authentication successful.',
                'owner': OwnerPublicSerializer(owner).data,
                'access': str(refresh.access_token),
                'refresh': str(refresh),
            },
            status=status.HTTP_200_OK,
        )


class OwnerProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({'owner': OwnerPublicSerializer(request.user).data}, status=status.HTTP_200_OK)

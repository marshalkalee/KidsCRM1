from django.shortcuts import render


def home(request):
    return render(request, "platform/home.html")


def login_view(request):
    return render(request, "auth/login.html")

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required

def home(request):
    """Home page - shows login if not authenticated, redirects to portal if authenticated"""
    if request.user.is_authenticated:
        return redirect('portal')
    return render(request, 'home.html')

@login_required
def portal(request):
    """User portal page - only accessible when logged in"""
    return render(request, 'portal.html')

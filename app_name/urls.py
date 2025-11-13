"""
URL configuration for your_app_name project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from django.views.generic import RedirectView
from django.urls import path, re_path

urlpatterns = [
    path('admin/', admin.site.urls),

    # These URLs shadow django-allauth URLs to shut them down:
    path('password/change/', RedirectView.as_view(url='/')),
    path('password/set/', RedirectView.as_view(url='/')),
    path('password/reset/', RedirectView.as_view(url='/')),
    path('password/reset/done/', RedirectView.as_view(url='/')), re_path('^password/reset/key/(?P<uidb36>[0-9A-Za-z]+)-(?P<key>.+)/$', RedirectView.as_view(url='/')),
    path('password/reset/key/done/', RedirectView.as_view(url='/')),
    path('email/', RedirectView.as_view(url='/')),
    path('confirm-email/', RedirectView.as_view(url='/')),
    re_path('^confirm-email/(?P<key>[-:\\w]+)/$',
            RedirectView.as_view(url='/')),
    path('accounts/signup/', RedirectView.as_view(url='/')),
    path('accounts/', include('allauth.urls')),
    # Add your app URLs here
    path('', include('your_app_name_app.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if settings.DEBUG:
    import debug_toolbar
    urlpatterns += [
        path('__debug__/', include(debug_toolbar.urls)),
    ]
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

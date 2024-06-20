# Copyright: (c) ccx0lw. https://github.com/ccx0lw/spug
# Copyright: (c) <fcjava@163.com>
# Released under the AGPL-3.0 License.
from django.urls import path

from .views import *

urlpatterns = [
    path('', DockerImageView.as_view()),
    path('<int:r_id>/', get_detail),
    path('request/', get_requests),
]

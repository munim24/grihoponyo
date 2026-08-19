from .models import Category
from .cart import Cart

def categories(request):
    return {
        'nav_categories': Category.objects.all()
    }

def cart(request):
    return {
        'cart': Cart(request)
    }
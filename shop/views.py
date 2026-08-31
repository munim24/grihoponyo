import random
import string
from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.http import require_POST
from .models import Category, Product, Order, OrderItem,  PromoCode, Advertisement
from .cart import Cart
from pages.models import Review
from django.http import JsonResponse
from decimal import Decimal
from django.core.mail import send_mail
from django.conf import settings
from django.db.models import Q
from django.utils import timezone



def home(request):
    cart = Cart(request)
    categories = Category.objects.all()
    products = Product.objects.filter(is_active=True, is_best_selling=True)[:5]
    reviews = Review.objects.filter(is_approved=True).order_by('-created_at')[:10]
    ads = Advertisement.objects.filter(is_active=True)

    flash_qs = Product.objects.filter(
        is_active=True, is_flash_sale=True, flash_sale_end__gt=timezone.now()
    ).order_by('flash_sale_end')
    flash_sale_products = flash_qs[:8]
    flash_sale_end = flash_qs.first().flash_sale_end if flash_qs.exists() else None

    category_products = []
    for cat in categories:
        cat_products = Product.objects.filter(category=cat, is_active=True)[:5]
        if cat_products:
            category_products.append({'category': cat, 'products': cat_products})

    context = {
        'categories': categories,
        'products': products,
        'cart': cart,
        'category_products': category_products,
        'reviews': reviews,
        'flash_sale_products': flash_sale_products,
        'flash_sale_end': flash_sale_end,
        'ads': ads,
    }
    return render(request, 'home.html', context)


def category_detail(request, slug):
    cart = Cart(request)
    category = get_object_or_404(Category, slug=slug)
    products = Product.objects.filter(category=category, is_active=True)
    context = {
        'category': category,
        'products': products,
        'cart': cart,
    }
    return render(request, 'shop/category.html', context)

def product_detail(request, slug):
    cart = Cart(request)
    product = get_object_or_404(Product, slug=slug, is_active=True)
    context = {
        'product': product,
        'cart': cart,
    }
    return render(request, 'shop/product_detail.html', context)



@require_POST
def cart_add(request, product_id):
    cart = Cart(request)
    product = get_object_or_404(Product, id=product_id)
    quantity = int(request.POST.get('quantity', 1))
    cart.add(product=product, quantity=quantity)

    if _is_ajax(request):
        return JsonResponse({
            'quantity': cart.get_quantity(product.id),
            'cart_count': len(cart),
            'cart_total': str(cart.get_total_price()),
        })
    return redirect('shop:cart_detail')



@require_POST
def cart_remove(request, product_id):
    cart = Cart(request)
    product = get_object_or_404(Product, id=product_id)
    cart.remove(product)

    if _is_ajax(request):
        return JsonResponse({
            'quantity': 0,
            'cart_count': len(cart),
            'cart_total': str(cart.get_total_price()),
        })
    return redirect('shop:cart_detail')



@require_POST
def cart_update(request, product_id):
    cart = Cart(request)
    product = get_object_or_404(Product, id=product_id)
    quantity = int(request.POST.get('quantity', 1))

    if quantity > 0:
        cart.add(product=product, quantity=quantity, update_quantity=True)
    else:
        cart.remove(product)

    if _is_ajax(request):
        return JsonResponse({
            'quantity': cart.get_quantity(product.id),
            'cart_count': len(cart),
            'cart_total': str(cart.get_total_price()),
        })
    return redirect('shop:cart_detail')



def cart_detail(request):
    cart = Cart(request)
    return render(request, 'shop/cart.html', {'cart': cart})


def search_suggestions(request):
    query = request.GET.get('q', '').strip()
    results = []
    if query:
        products = Product.objects.filter(
            Q(name__icontains=query) |
            Q(description__icontains=query) |
            Q(search_keywords__icontains=query) |
            Q(category__name__icontains=query),
            is_active=True
        ).distinct()[:6]
        for p in products:
            price = p.discount_price if p.discount_price else p.price
            results.append({
                'name': p.name,
                'price': str(price),
                'url': f'/product/{p.slug}/',
                'image': p.image.url if p.image else '',
            })
    return JsonResponse({'results': results})



def generate_order_id():
    date_part = timezone.now().strftime('%y%m%d')
    last_order = Order.objects.filter(
        order_id__startswith=f'BA-{date_part}-'
    ).order_by('-id').first()

    if last_order:
        last_seq = int(last_order.order_id.split('-')[-1])
        next_seq = last_seq + 1
    else:
        next_seq = 1

    return f'BA-{date_part}-{next_seq:04d}'



DELIVERY_CHARGES = {
          'dhaka': Decimal('80'), 
          'outside': Decimal('140')
    }

def checkout(request):
    cart = Cart(request)
    if len(cart) == 0:
        return redirect('shop:cart_detail')

    subtotal = cart.get_total_price()
    promo_code = request.session.get('promo_code', '')
    discount_amount = Decimal(request.session.get('promo_discount', '0'))
    delivery_area = request.session.get('delivery_area', 'dhaka')
    if delivery_area not in DELIVERY_CHARGES:
        delivery_area = 'dhaka'
    delivery_charge = DELIVERY_CHARGES[delivery_area]
    final_total = subtotal - discount_amount + delivery_charge

    if request.method == 'POST':
        delivery_area = request.POST.get('delivery_area', delivery_area)
        if delivery_area not in DELIVERY_CHARGES:
            delivery_area = 'dhaka'
        delivery_charge = DELIVERY_CHARGES[delivery_area]
        final_total = subtotal - discount_amount + delivery_charge

        full_name = request.POST.get('full_name')
        phone = request.POST.get('phone')
        address = request.POST.get('address')

        order_id = generate_order_id()
        while Order.objects.filter(order_id=order_id).exists():
            order_id = generate_order_id()

        order = Order.objects.create(
            order_id=order_id,
            full_name=full_name,
            phone=phone,
            address=address,
            subtotal=subtotal,
            promo_code=promo_code,
            discount_amount=discount_amount,
            delivery_area=delivery_area,
            delivery_charge=delivery_charge,
            total_amount=final_total,
        )

        order_items_text = ""
        for item in cart:
            OrderItem.objects.create(
                order=order,
                product=item['product'],
                quantity=item['quantity'],
                price=item['price'],
            )
            order_items_text += f"- {item['product'].name} x {item['quantity']} = ৳{item['total_price']}\n"

        area_label = 'Inside Dhaka' if delivery_area == 'dhaka' else 'Outside Dhaka'
        email_body = f"""New Order Received!

                    Order ID: {order.order_id}
                    Customer: {full_name}
                    Phone: {phone}
                    Address: {address}

                    Items:
                    {order_items_text}
                    Subtotal: ৳{subtotal}
                    Discount: ৳{discount_amount} ({promo_code if promo_code else 'No promo'})
                    Delivery ({area_label}): ৳{delivery_charge}
                    Total: ৳{final_total}
                    """
        try:
            send_mail(
                subject=f'New Order #{order.order_id} - Grihoponyo',
                message=email_body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[settings.ADMIN_EMAIL],
                fail_silently=True,
            )
        except Exception:
            pass

        cart.clear()
        request.session.pop('promo_code', None)
        request.session.pop('promo_discount', None)
        request.session.pop('delivery_area', None)

        return redirect('shop:order_success', order_id=order.order_id)

    context = {
        'cart': cart,
        'subtotal': subtotal,
        'promo_code': promo_code,
        'discount_amount': discount_amount,
        'delivery_area': delivery_area,
        'delivery_charge': delivery_charge,
        'final_total': final_total,
    }
    return render(request, 'shop/checkout.html', context)


@require_POST
def set_delivery_area(request):
    area = request.POST.get('delivery_area', 'dhaka')
    if area not in DELIVERY_CHARGES:
        area = 'dhaka'
    request.session['delivery_area'] = area

    cart = Cart(request)
    subtotal = cart.get_total_price()
    discount_amount = Decimal(request.session.get('promo_discount', '0'))
    delivery_charge = DELIVERY_CHARGES[area]
    final_total = subtotal - discount_amount + delivery_charge

    return JsonResponse({
        'success': True,
        'delivery_charge': str(delivery_charge),
        'new_total': str(final_total),
    })




def order_success(request, order_id):
    order = get_object_or_404(Order, order_id=order_id)
    return render(request, 'shop/order_success.html', {'order': order})



def _is_ajax(request):
    return request.headers.get('x-requested-with') == 'XMLHttpRequest'



def apply_promo(request):
    if request.method == 'POST':
        code = request.POST.get('promo_code', '').strip().upper()
        cart = Cart(request)

        try:
            promo = PromoCode.objects.get(code=code, is_active=True)
        except PromoCode.DoesNotExist:
            return JsonResponse({'success': False, 'message': 'Invalid or expired promo code.'})

        from django.utils import timezone
        if promo.valid_till and promo.valid_till < timezone.now().date():
            return JsonResponse({'success': False, 'message': 'This promo code has expired.'})

        subtotal = cart.get_total_price()
        discount = (subtotal * promo.discount_percent) / 100
        if promo.max_discount_amount and discount > promo.max_discount_amount:
            discount = promo.max_discount_amount

        request.session['promo_code'] = promo.code
        request.session['promo_discount'] = str(discount)

        return JsonResponse({
            'success': True,
            'message': f'Promo applied! {promo.discount_percent}% off.',
            'discount': str(discount),
            'new_total': str(subtotal - discount),
        })

    return JsonResponse({'success': False, 'message': 'Invalid request.'})


def remove_promo(request):
    request.session.pop('promo_code', None)
    request.session.pop('promo_discount', None)
    return JsonResponse({'success': True})



def track_order(request):
    phone = request.GET.get('phone', '').strip()
    orders = None
    searched = False

    if phone:
        searched = True
        orders = Order.objects.filter(phone=phone).order_by('-created_at')

    context = {
        'phone': phone,
        'orders': orders,
        'searched': searched,
    }
    return render(request, 'shop/track_order.html', context)



@require_POST
def buy_now(request, product_id):
    cart = Cart(request)
    product = get_object_or_404(Product, id=product_id)
    cart.add(product=product, quantity=1)
    return redirect('shop:checkout')


def combo_offers(request):
    cart = Cart(request)
    products = Product.objects.filter(is_active=True, is_combo_offer=True)
    context = {
        'products': products,
        'cart': cart,
    }
    return render(request, 'shop/combo_offers.html', context)
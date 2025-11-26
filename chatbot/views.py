from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.conf import settings
import json
import requests
from .models import Phone, Order


def index(request):
    """Intro/welcome page"""
    return render(request, 'chatbot/index.html')


def chatbot_view(request):
    """Main chatbot page"""
    return render(request, 'chatbot/chatbot.html')


def phones_api(request):
    """API endpoint to get list of available phones"""
    phones = Phone.objects.filter(is_available=True, stock__gt=0)
    phone_list = []
    for phone in phones:
        phone_list.append({
            'id': phone.id,
            'name': phone.name,
            'brand': phone.brand,
            'model': phone.model,
            'price_php': float(phone.price_php),
            'description': phone.description,
            'stock': phone.stock,
        })
    return JsonResponse({'phones': phone_list})


@csrf_exempt
@require_http_methods(["POST"])
def chat_api(request):
    """API endpoint to handle chatbot messages using OpenRouter"""
    try:
        data = json.loads(request.body)
        user_message = data.get('message', '')
        
        # Get available phones for context
        phones = Phone.objects.filter(is_available=True, stock__gt=0)
        phones_context = "\n".join([
            f"- {p.brand} {p.model}: ₱{p.price_php:,.2f} ({p.stock} in stock) - {p.description}"
            for p in phones
        ])
        
        # System prompt for the AI assistant
        system_prompt = f"""You are a helpful AI assistant for PhoneXpress, an online phone shop in the Philippines. 
Your role is to:
1. Help customers find the right phone based on their needs and budget
2. Provide information about available phones
3. Assist with ordering phones
4. Answer questions about phones, prices, and shipping

Available phones:
{phones_context}

Important:
- All prices are in Philippine Peso (PHP/₱)
- Always mention prices in PHP format (e.g., ₱25,999.00)
- Be friendly, professional, and helpful
- If a customer wants to order, guide them to provide: name, email, phone number, shipping address, and which phone they want
- You can suggest phones based on budget or needs
- Check stock availability before confirming orders

Current conversation context is maintained through the chat history."""
        
        # Prepare the request to OpenRouter API
        openrouter_url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        }
        
        # Get chat history if available
        chat_history = data.get('history', [])
        
        # Build messages for the API
        messages = [{"role": "system", "content": system_prompt}]
        
        # Add chat history (last 10 messages to avoid token limits)
        for msg in chat_history[-10:]:
            messages.append({
                "role": msg.get("role", "user"),
                "content": msg.get("content", "")
            })
        
        # Add current user message
        messages.append({"role": "user", "content": user_message})
        
        payload = {
            "model": "openai/gpt-3.5-turbo",
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 500,
        }
        
        # Make request to OpenRouter
        response = requests.post(openrouter_url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        
        result = response.json()
        ai_message = result['choices'][0]['message']['content']
        
        return JsonResponse({
            'response': ai_message,
            'success': True
        })
        
    except requests.RequestException as e:
        return JsonResponse({
            'response': 'Sorry, I encountered an error. Please try again.',
            'success': False,
            'error': str(e)
        }, status=500)
    except Exception as e:
        return JsonResponse({
            'response': 'Sorry, something went wrong. Please try again.',
            'success': False,
            'error': str(e)
        }, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def create_order(request):
    """API endpoint to create a new order"""
    try:
        data = json.loads(request.body)
        
        phone_id = data.get('phone_id')
        quantity = int(data.get('quantity', 1))
        customer_name = data.get('customer_name')
        customer_email = data.get('customer_email')
        customer_phone = data.get('customer_phone')
        shipping_address = data.get('shipping_address')
        
        # Validate required fields
        if not all([phone_id, customer_name, customer_email, customer_phone, shipping_address]):
            return JsonResponse({
                'success': False,
                'message': 'All fields are required'
            }, status=400)
        
        # Get phone
        try:
            phone = Phone.objects.get(id=phone_id, is_available=True)
        except Phone.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': 'Phone not found or not available'
            }, status=404)
        
        # Check stock
        if phone.stock < quantity:
            return JsonResponse({
                'success': False,
                'message': f'Only {phone.stock} units available in stock'
            }, status=400)
        
        # Calculate total price
        total_price = phone.price_php * quantity
        
        # Create order
        order = Order.objects.create(
            customer_name=customer_name,
            customer_email=customer_email,
            customer_phone=customer_phone,
            phone=phone,
            quantity=quantity,
            total_price_php=total_price,
            shipping_address=shipping_address,
            status='pending'
        )
        
        # Update stock
        phone.stock -= quantity
        if phone.stock == 0:
            phone.is_available = False
        phone.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Order placed successfully!',
            'order_id': order.id,
            'total_price_php': float(total_price)
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error creating order: {str(e)}'
        }, status=500)


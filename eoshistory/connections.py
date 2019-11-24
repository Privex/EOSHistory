from typing import Tuple

import pika
from django.conf import settings
from pika.adapters.blocking_connection import BlockingChannel


def get_rmq(**kwargs) -> Tuple[BlockingChannel, pika.BlockingConnection]:
    """Get a RabbitMQ channel + connection"""
    host = kwargs.pop('host', settings.RMQ_HOST)
    
    params = [
        pika.ConnectionParameters(host=host, **kwargs)
    ]
    connection = pika.BlockingConnection(params)
    channel = connection.channel()
    return channel, connection


def get_rmq_queue(queue=settings.RMQ_QUEUE, **kwargs) -> Tuple[BlockingChannel, pika.BlockingConnection]:
    channel, connection = get_rmq(**kwargs)
    
    # Declare the queue
    q = channel.queue_declare(queue=queue, durable=True, exclusive=False, auto_delete=False)
    
    # Turn on delivery confirmations
    channel.confirm_delivery()
    return channel, connection


def get_celery_message_count(queue=settings.DEFAULT_CELERY_QUEUE, **kwargs):
    channel, connection = get_rmq(**kwargs)
    q = channel.queue_declare(queue, durable=True)
    msg_count = int(q.method.message_count)
    connection.close()
    return msg_count


"""Erros que mudam o que o consumer faz com a mensagem do RabbitMQ."""


class RequeueJob(Exception):
    """O job não foi feito, mas não falhou: a mensagem volta para a fila (nack com requeue).

    Ex.: nenhuma extensão pegou o job a tempo. A mensagem mantém a expiração original
    (MessageTtl da API), então um job que ninguém pega acaba expirando em vez de girar
    para sempre.
    """

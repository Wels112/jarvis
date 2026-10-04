# -*- coding: utf-8 -*-
"""Сетевые особенности этой машины.

IPv6 здесь не маршрутизируется: DNS отдаёт адреса IPv6, а подключение к ним
висит до таймаута. requests лечится точечно (urllib3), но живой разговор идёт
через websockets внутри библиотеки Google, куда параметр не пробросить. Поэтому
на весь процесс подменяется разрешение имён: если семейство адресов не задано
явно — сначала IPv4.
"""
import socket

_patched = False


def prefer_ipv4():
    global _patched
    if _patched:
        return
    original = socket.getaddrinfo

    def getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        if family in (0, socket.AF_UNSPEC):
            try:
                return original(host, port, socket.AF_INET, type, proto, flags)
            except socket.gaierror:
                pass                      # у адреса нет IPv4 — пусть решает система
        return original(host, port, family, type, proto, flags)

    socket.getaddrinfo = getaddrinfo
    _patched = True

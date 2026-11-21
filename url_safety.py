import ipaddress
import socket

import httpx

GLOBAL_IPV6 = ipaddress.ip_network("2000::/3")
AZURE_PLATFORM_IP = ipaddress.ip_address("168.63.129.16")


def public_ip(value):
    address = ipaddress.ip_address(value)
    return (
        address.is_global
        and not address.is_multicast
        and not address.is_reserved
        and address != AZURE_PLATFORM_IP
        and (address.version == 4 or address in GLOBAL_IPV6)
        and not getattr(address, "ipv4_mapped", None)
        and not getattr(address, "sixtofour", None)
        and not getattr(address, "teredo", None)
    )


def parse_url(value):
    try:
        url = httpx.URL(value)
    except (httpx.InvalidURL, ValueError) as exc:
        raise ValueError("Invalid HTTP(S) URL") from exc

    if url.scheme not in {"http", "https"} or not url.host:
        raise ValueError("An absolute HTTP(S) URL is required")
    if url.userinfo or "@" in value.split("://", 1)[-1].split("/", 1)[0]:
        raise ValueError("URL credentials are not allowed")
    if url.fragment or "#" in value:
        raise ValueError("URL fragments are not allowed")
    if url.port not in (None, 443 if url.scheme == "https" else 80):
        raise ValueError("Only the default HTTP and HTTPS ports are allowed")

    host = url.host.rstrip(".").lower()
    if "%" in host:
        raise ValueError("Scoped or encoded hosts are not allowed")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if "." not in host or host.endswith((".localhost", ".local", ".internal", ".home.arpa")):
            raise ValueError("A public host is required")
    else:
        if not public_ip(host):
            raise ValueError("A public IP address is required")
    return url


def resolve_public_ip(url):
    host = url.raw_host.decode("ascii").rstrip(".")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        records = socket.getaddrinfo(host, url.port or (443 if url.scheme == "https" else 80),
                                     type=socket.SOCK_STREAM)
        addresses = list(dict.fromkeys(record[4][0] for record in records))
    else:
        addresses = [host]
    if not addresses or not all(public_ip(address) for address in addresses):
        raise ValueError("The host must resolve only to public IP addresses")
    return addresses[0]

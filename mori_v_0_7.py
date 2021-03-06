"""
@project : Mori
@author  : zhang_xinjian
@mail   : zxjlm233@163.com
@ide    : PyCharm
@time   : 2020-11-17 19:23:27
@description: None
"""

import requests
import json
import re
from requests_futures.sessions import FuturesSession
import time
from rich.console import Console
from rich.traceback import Traceback
import platform
from argparse import ArgumentParser, RawDescriptionHelpFormatter

from mori import regex_checker, data_render
from printer import ResultPrinter
from reporter import Reporter
from proxy import Proxy
from rich.progress import track

__version__ = 'v0.7'
module_name = "Mori Kokoro"


class MoriFuturesSession(FuturesSession):
    """
    自定义的FuturesSession类，主要是重写了request函数，使其具有统计链接请求时间的功能
    """

    def request(self, method, url, hooks=None, *args, **kwargs):
        """
        重写的request函数，添加hooks
        """
        if hooks is None:
            hooks = {}
        start = time.monotonic()

        def response_time(resp, *args_sub, **kwargs_sub):
            """
            计算准确的请求时间
            """
            _, _ = args_sub, kwargs_sub
            resp.elapsed = time.monotonic() - start
            return

        hooks['response'] = [response_time]

        return super(MoriFuturesSession, self).request(method,
                                                       url,
                                                       hooks=hooks,
                                                       *args, **kwargs)





def get_response(request_future, site_data):
    """
    对response进行初步处理
    """
    response = None
    check_result = 'Damage'
    check_results = {}
    traceback = None
    resp_text = ''

    try:
        response = request_future.result()
        exception_text = getattr(response, 'exceptions', None)
        error_context = getattr(response, 'error_context', None)

        if response:
            resp_text = response.text
        else:
            return

        resp_json = {}

        if site_data.get('decrypt') and resp_text:
            try:
                import importlib
                package = importlib.import_module(
                    'decrypt.' + site_data['decrypt'])
                Decrypt = getattr(package, 'Decrypt')
                resp_text = Decrypt().decrypt(resp_text)
            except Exception as _e:
                traceback = Traceback()
                error_context = 'json decrypt error'
                exception_text = _e

        if resp_text:
            try:
                # 有些键可能值是null,这种实际上是可以通过判断逻辑的,所以使用占位符(placeholder)来解除null
                resp_json = json.loads(
                    re.search('({.*})', resp_text.replace('\\', '').replace('null', '"placeholder"')).group(1))
            except Exception as _e:
                traceback = Traceback()
                error_context = 'response data not json format'
                exception_text = _e
            try:
                check_results = {regex: regex_checker(
                    regex, resp_json, site_data.get('exception'))
                    for regex in site_data['regex']}

                if list(check_results.values()) != ['OK'] * len(check_results):
                    error_context = 'regex failed'
                else:
                    check_result = 'OK'

            except Exception as _e:
                traceback = Traceback()
                error_context = 'json decrypt error'
                exception_text = _e
    except requests.exceptions.HTTPError as errh:
        error_context = "HTTP Error"
        exception_text = str(errh)
    except requests.exceptions.ProxyError as errp:
        # site_data['request_future']
        error_context = "Proxy Error"
        exception_text = str(errp)
    except requests.exceptions.ConnectionError as errc:
        error_context = "Error Connecting"
        exception_text = str(errc)
    except requests.exceptions.Timeout as errt:
        error_context = "Timeout Error"
        exception_text = str(errt)
    except requests.exceptions.RequestException as err:
        error_context = "Unknown Error"
        exception_text = str(err)

    return response, error_context, exception_text, check_results, check_result, traceback, resp_text


def mori(site_datas, result_printer, timeout, use_proxy) -> list:
    """
    主处理函数
    """
    if len(site_datas) >= 20:
        max_workers = 20
    else:
        max_workers = len(site_datas)

    session = MoriFuturesSession(
        max_workers=max_workers, session=requests.Session())

    results_total = []

    for site_data in track(site_datas, description="Preparing..."):

        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.12; rv:55.0) Gecko/20100101 Firefox/55.0',
        }

        if site_data.get('headers'):
            if isinstance(site_data.get('headers'), dict):
                headers.update(site_data.get('headers'))

        Proxy.set_proxy_url(site_data.get('proxy'), site_data.get('strict_proxy'), use_proxy, headers)

        if site_data.get('antispider') and site_data.get('data'):
            try:
                import importlib
                package = importlib.import_module('antispider.' + site_data['antispider'])
                Antispider = getattr(package, 'Antispider')
                site_data['data'], headers = Antispider(
                    site_data['data'], headers).processor()
            except Exception as _e:
                site_data['single'] = True
                site_data['error_text'] = 'antispider failed'
                site_data['exception_text'] = _e
                site_data['traceback'] = Traceback()
                continue

        try:
            proxies = Proxy.get_proxy()
        except Exception as _e:
            site_data['single'] = True
            site_data['error_text'] = 'all of six proxies can`t be used'
            site_data['exception_text'] = _e
            site_data['traceback'] = Traceback()
            continue
        if site_data.get('data'):
            if re.search(r'application.json', headers.get('Content-Type', '')):
                site_data["request_future"] = session.post(
                    site_data['url'], json=site_data['data'], headers=headers, timeout=timeout, proxies=proxies,
                    allow_redirects=True)
            else:
                site_data["request_future"] = session.post(
                    site_data['url'], data=site_data['data'], headers=headers, timeout=timeout, proxies=proxies,
                    allow_redirects=True)
        else:
            site_data["request_future"] = session.get(
                site_data['url'], headers=headers, timeout=timeout, proxies=proxies)

    for site_data in site_datas:
        traceback, r, resp_text = None, None, ''
        error_text, exception_text, check_result, check_results = '', '', 'Unknown', {}
        try:
            if site_data.get('single'):
                check_result = 'Damage'
                error_text = site_data['error_text']
                exception_text = site_data['exception_text']
                traceback = site_data['traceback']
            else:
                future = site_data["request_future"]
                r, error_text, exception_text, check_results, check_result, traceback, resp_text = get_response(
                    request_future=future,
                    site_data=site_data)

            result = {
                'name': site_data['name'],
                'url': site_data['url'],
                'base_url': site_data.get('base_url', ''),
                'resp_text': resp_text if len(
                    resp_text) < 500 else 'too long, and you can add --xls to see detail in *.xls file',
                'status_code': r and r.status_code,
                'time(s)': r.elapsed if r else -1,
                'error_text': error_text,
                'expection_text': exception_text,
                'check_result': check_result,
                'traceback': traceback,
                'check_results': check_results,
                'remark': site_data.get('remark', '')
            }

            rel_result = dict(result.copy())
            rel_result['resp_text'] = resp_text

        except Exception as error:
            result = {
                'name': site_data['name'],
                'url': site_data['url'],
                'base_url': site_data.get('base_url', ''),
                'resp_text': resp_text if len(
                    resp_text) < 500 else 'too long, and you can add --xls to see detail in *.xls file',
                'status_code': r and r.status_code,
                'time(s)': r.elapsed if r else -1,
                'error_text': error or 'site handler error',
                'check_result': check_result,
                'traceback': Traceback(),
                'check_results': check_results,
                'remark': site_data.get('remark', '')
            }
            rel_result = result.copy()

        results_total.append(rel_result)
        result_printer.printer(result)

    return results_total


def timeout_check(value):
    """
    检查是否超时
    """
    from argparse import ArgumentTypeError

    try:
        timeout = float(value)
    except Exception as _:
        raise ArgumentTypeError(f"Timeout '{value}' must be a number.")
    if timeout <= 0:
        raise ArgumentTypeError(
            f"Timeout '{value}' must be greater than 0.0s.")
    return timeout


def send_mail(receivers: list, file_content, html, subject, mail_host, mail_user, mail_pass, mail_port=0):
    """
    发送邮件
    配置信息见README
    """
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    sender = mail_user
    message = MIMEMultipart()
    message['From'] = sender
    message['To'] = ';'.join(receivers)
    message['Subject'] = subject

    if html:
        message.attach(MIMEText(html, 'html', 'utf-8'))

    part = MIMEText(file_content.getvalue(), "vnd.ms-excel", 'utf-8')
    part.add_header('Content-Disposition', 'attachment',
                    filename=f'{subject}.xls')
    message.attach(part)

    for count in range(4):
        try:
            if mail_port == 0:
                smtp = smtplib.SMTP()
                smtp.connect(mail_host)
            else:
                smtp = smtplib.SMTP_SSL(mail_host, mail_port)
            smtp.ehlo()
            smtp.login(mail_user, mail_pass)
            smtp.sendmail(sender, receivers, message.as_string())
            smtp.close()
            break
        except Exception as _e:
            print(_e)
            if count == 3:
                raise Exception('failed to send email')


def main():
    """
    入口
    """

    version_string = f"%(prog)s {__version__}\n" + \
                     f"requests:  {requests.__version__}\n" + \
                     f"Python:  {platform.python_version()}"

    parser = ArgumentParser(formatter_class=RawDescriptionHelpFormatter,
                            description=f"{module_name} (Version {__version__})"
                            )
    parser.add_argument("--version",
                        action="version", version=version_string,
                        help="Display version information and dependencies."
                        )
    parser.add_argument("--verbose", "-v", "-d", "--debug",
                        action="store_true", dest="verbose", default=False,
                        help="Display extra debugging information and metrics."
                        )
    parser.add_argument("--xls",
                        action="store_true", dest="xls", default=False,
                        help="Create .xls File.(Microsoft Excel file format)"
                        )
    parser.add_argument("--show-all-site",
                        action="store_true",
                        dest="show_site_list", default=False,
                        help="Show all infomations of the apis in files."
                        )
    parser.add_argument("--json", "-j", metavar="JSON_FILE",
                        dest="json_file", default=None,
                        help="Load data from a local JSON file.")
    parser.add_argument("--email", "-e",
                        # metavar="EMAIL",
                        action="store_true",
                        dest="email", default=False,
                        help="Send email to mailboxes in the file 'config.py'.")
    parser.add_argument("--print-invalid",
                        action="store_false", dest="print_invalid", default=False,
                        help="Output api(s) that was invalid."
                        )
    parser.add_argument("--no-proxy", default=True,
                        action="store_false", dest="use_proxy",
                        help="Use proxy.Proxy should define in config.py"
                        )
    parser.add_argument("--timeout",
                        action="store", metavar='TIMEOUT',
                        dest="timeout", type=timeout_check, default=None,
                        help="Time (in seconds) to wait for response to requests. "
                             "Default timeout is 30s. "
                             "A longer timeout will be more likely to get results from slow sites. "
                             "On the other hand, this may cause a long delay to gather all results."
                        )

    args = parser.parse_args()

    console = Console()

    file_path = args.json_file or './apis.json'

    with open(file_path, 'r', encoding='utf-8') as f:
        apis = json.load(f)
    console.print(f'[green] read file {file_path} success~')
    data_render(apis)

    if args.show_site_list:

        keys_to_show = ['name', 'url', 'data']
        apis_to_show = list(map(lambda api: {key: value for key, value in api.items() if key in keys_to_show}, apis))
        console.print(apis_to_show)

    else:
        r = r'''
             __  __               _   _  __        _
            |  \/  |  ___   _ __ (_) | |/ /  ___  | | __  ___   _ __   ___
            | |\/| | / _ \ | '__|| | | ' /  / _ \ | |/ / / _ \ | '__| / _ \
            | |  | || (_) || |   | | | . \ | (_) ||   < | (_) || |   | (_) |
            |_|  |_| \___/ |_|   |_| |_|\_\ \___/ |_|\_\ \___/ |_|    \___/
            '''
        print(r)

        result_printer = ResultPrinter(
            args.verbose, args.print_invalid, console)

        # start = time.perf_counter()
        # for _ in range(20):
        results = mori(apis, result_printer, timeout=args.timeout or 30, use_proxy=args.use_proxy)
        # use_time = time.perf_counter() - start
        # print('total_use_time:{}'.format(use_time))

        if args.xls or args.email:
            for i, result in enumerate(results):
                results[i]['check_results'] = '\n'.join(
                    [f'{key} : {value}' for key, value in result['check_results'].items()])

            repo = Reporter(['name', 'url', 'base_url', 'status_code', 'time(s)',
                             'check_result', 'check_results', 'error_text', 'remark', 'resp_text'], results)

            if args.xls:
                console.print('[cyan]now generating report...')

                repo.processor()

                console.print('[green]mission completed')

            if args.email:
                try:
                    import config
                except Exception as _e:
                    console.print(
                        'can`t get config.py file, please read README.md, search keyword [red]config.py', _e)
                    return
                console.print('[cyan]now sending email...')

                fs = repo.processor(is_stream=True)
                html = repo.generate_table()
                try:
                    send_mail(config.RECEIVERS, fs, html, config.MAIL_SUBJECT, config.MAIL_HOST,
                              config.MAIL_USER, config.MAIL_PASS, getattr(config, 'MAIL_PORT', 0))

                    console.print('[green]mission completed')
                except Exception as _e:
                    console.print(f'[red]mission failed,{_e}')


if __name__ == "__main__":
    main()

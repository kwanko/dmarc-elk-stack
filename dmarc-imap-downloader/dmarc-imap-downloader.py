#!/usr/bin/python3

import sys
import email
import re
import os
import gzip
import zipfile
import io
import logging
import logging.handlers
import argparse
from imapclient import IMAPClient

# ------------------------------------------------------------------------------

LOG = logging.getLogger('logger')
LOG.setLevel(logging.INFO)
DEFAULT_FORMAT = logging.Formatter("%(asctime)s %(levelname)-8s: %(message)s",
                                   "%H:%M:%S")
STDOUT_STREAM_HANDLER = logging.StreamHandler(sys.stdout)
STDOUT_STREAM_HANDLER.setFormatter(DEFAULT_FORMAT)
LOG.addHandler(STDOUT_STREAM_HANDLER)

# ------------------------------------------------------------------------------


def extract_dmarc_reports(imap_server, user, password, imap_folder,
                          report_directory):
    server = IMAPClient(imap_server, use_uid=True)
    server.login(user, password)
    select_info = server.select_folder(imap_folder)
    LOG.info('{} messages in {}'.format(select_info[b'EXISTS'], imap_folder))

    messages = server.search([u'UNSEEN'])
    LOG.info("{} unseen messages to process".format(len(messages)))

    attachments = []
    valid_message_counter = 0
    for msgid, data in server.fetch(messages, ['ENVELOPE', 'RFC822']).items():
        envelope = data[b'ENVELOPE']
        email_message = email.message_from_bytes(data[b'RFC822'])
        LOG.debug('ID #{}: "{}" received {} / multipart: {} / disposition: {} / content-type: {}'.format(msgid, envelope.subject.decode(), envelope.date, email_message.is_multipart(), email_message.get_content_disposition(), email_message.get_content_type()))
        if email_message.is_multipart():
            for attachement in email_message.get_payload():
                if attachement.get_content_disposition() == 'attachment':
                    LOG.debug('\t{}: {}'.format(attachement.get_content_type(), attachement.get_filename()))
                    data = attachement.get_payload(decode=True)
                    filename = attachement.get_filename()
                    attachments.append({
                        'filename': filename,
                        'data': data,
                        'email': email_message,
                        'envelope': envelope,
                    })
            valid_message_counter += 1
        elif email_message.get_content_disposition() == 'attachment':
            data = email_message.get_payload(decode=True)
            filename = email_message.get_filename()
            attachments.append({
                'filename': filename,
                'data': data,
                'email': email_message,
                'envelope': envelope,
            })
            valid_message_counter += 1
        else:
            LOG.warning('skipping invalid email <{} | Subject: {}>'.format(envelope.date, envelope.subject.decode()))

    valid_report_filename_regex = re.compile('^([a-zA-Z0-9\-]+\.?)+!([a-zA-Z0-9\-]+\.?)+!\d{10}!\d{10}(![a-zA-Z0-9\-]+)?\.xml$')
    valid_attachment_filename_regex = re.compile('^([a-zA-Z0-9\-]+\.?)+!([a-zA-Z0-9\-]+\.?)+!\d{10}!\d{10}(![a-zA-Z0-9\-]+)?\.(xml|xml\.gz|zip)$')
    dmarc_reports = []
    for attachment in attachments:
        filename = attachment['filename']
        email_info = attachment['email']
        data = attachment['data']
        envelope = attachment['envelope']
        if not valid_attachment_filename_regex.match(filename):
            LOG.warning("invalid attachment name format <{}> from email <{} | Subject: {}>".format(filename, envelope.date, envelope.subject.decode()))
            continue
        if filename.endswith('.xml.gz'):
            report_filename = filename[:-3]
            xml_data = gzip.decompress(data).decode()
            dmarc_reports.append({
                'attachment_infos': attachment,
                'xml': xml_data.strip(),
                'report_filename': report_filename,
            })
        elif filename.endswith('.zip'):
            zip_data = io.BytesIO(data)
            if not zipfile.is_zipfile(zip_data):
                LOG.warning("invalid zip file <{}> from email <{} | Subject: {}>".format(filename, envelope.date, envelope.subject.decode()))
                continue
            with zipfile.ZipFile(zip_data) as zip_file:
                for report_filename in zip_file.namelist():
                    if not valid_report_filename_regex.match(report_filename):
                        LOG.warning("invalid report filename <{}> in attachment <{}> from email <{} | Subject: {}>".format(report_filename, filename, envelope.date, envelope.subject.decode()))
                        continue
                    xml_data = zip_file.read(report_filename).decode()
                    dmarc_reports.append({
                        'attachment_infos': attachment,
                        'xml': xml_data.strip(),
                        'report_filename': report_filename,
                    })
        elif filename.endswith('.xml'):
            dmarc_reports.append({
                'attachment_infos': attachment,
                'xml': data.strip(),
                'report_filename': filename,
            })

    if not os.path.isdir(report_directory):
        raise Exception('Directory <{}> does not exists'.format(report_directory))

    already_exist_counter = 0
    for report in dmarc_reports:
        report_filename = report['report_filename']
        xml_data = report['xml']
        envelope = report['attachment_infos']['envelope']
        reception_daystamp = envelope.date.strftime('%Y-%m-%d')
        dirpath = os.path.join(report_directory, reception_daystamp)
        os.makedirs(dirpath, mode=0o755, exist_ok=True)
        filepath = os.path.join(dirpath, report_filename)
        if os.path.exists(filepath):
            LOG.debug('file <{}> already present'.format(filepath))
            already_exist_counter += 1
            continue
        with open(filepath, "w") as report_file:
            LOG.debug('creating <{}>'.format(filepath))
            report_file.write(xml_data)

    LOG.info('{} reports processed in {} messages - {} reports already exists'.format(len(dmarc_reports), valid_message_counter, already_exist_counter))


if __name__ == '__main__':
    PARSER = argparse.ArgumentParser(description="DMARC report imap downloader")
    PARSER.add_argument('-d', '--debug', action='store_true', dest='debug')
    PARSER.add_argument('-s', '--imap-server', type=str, required=True,
                        help='imap server address (ex: imap.gmail.com)')
    PARSER.add_argument('-u', '--user', type=str, required=True)
    PARSER.add_argument('-p', '--password', type=str, required=True)
    PARSER.add_argument('-f', '--imap-folder', type=str, required=True,
                        help='imap folder/google tag where to find reports')
    PARSER.add_argument('-D', '--directory', type=str, required=True,
                        help='where to place downloaded reports')
    PARSER.add_argument('-l', '--log-file', type=str, required=False,
                        help='log to file instead of stdout')
    ARGS = PARSER.parse_args()

    LOG_FILE = getattr(ARGS, 'log_file', None)
    if LOG_FILE:
        ROTATING_FILE_HANDLER = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=1024*1024*10, backupCount=3)
        ROTATING_FILE_HANDLER.setFormatter(DEFAULT_FORMAT)
        LOG.removeHandler(STDOUT_STREAM_HANDLER)
        LOG.addHandler(ROTATING_FILE_HANDLER)

    if getattr(ARGS, 'debug'):
        LOG.setLevel(logging.DEBUG)
    LOG.debug(ARGS)

    IMAP_SERVER = getattr(ARGS, 'imap_server')
    USER = getattr(ARGS, 'user')
    PASSWORD = getattr(ARGS, 'password')
    IMAP_FOLDER = getattr(ARGS, 'imap_folder')
    REPORT_DIRECTORY = getattr(ARGS, 'directory')
    extract_dmarc_reports(IMAP_SERVER, USER, PASSWORD, IMAP_FOLDER, REPORT_DIRECTORY)

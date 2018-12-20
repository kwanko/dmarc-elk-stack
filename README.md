# dmarc-elk-stack

This repository contains logstash config and a kibana dashboard used to analyze DMARC reports.

The architecure is a classical ELK stack. The only specific part is the python script used to fetch and extract DMARC reports for logstash.

![Architecture](/images/architecture.png)

As said before, the python script `dmarc-imap-downloader.py` fetches DMARC reports over IMAP and extracts them into a specific directory organized by date. A cron task can be preiodicly scheduled:

```
0,30 * * * * root /var/lib/dmarc-imap-downloader/virtualenv/bin/python /var/lib/dmarc-imap-downloader/dmarc-imap-downloader.py -s <imap_mailserver> -u <account_user> -p <account_password> -f <imap_folder_or_gmail_tag> -D /var/cache/dmarc-reports -l /var/log/dmarc-imap-downloader.log >/var/log/dmarc-imap-downloader.cron.log 2>&1
```

Then, logstash scans periodicly fo new files in `/var/cache/dmarc-reports`. The new xml files are ingested and:

* splitted on each record found,
* data type is enforced for date and integers values,
* reverse DNS records are filled,
* geoip localization is added,
* and finally records are sent to the daily index in elasticsearch.

The kibana dashboard looks like that:

![DMARC statistics](/images/dashboard.png)

# Contribution

Feel free to reuse and modify as you wish. Contribution is welcomed too.

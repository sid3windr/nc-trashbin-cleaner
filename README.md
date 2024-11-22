# Introduction

Nextcloud has a useful "Deleted files" feature, which provides for an
automatic cleanup of any file that has been there for a specific amount of
days, plus some extras. However, some apps just create trash inside the
trash - for example, Joplin creates a high amount of lock files and
"timeCheck" files, which it then deletes, but they linger in the recycle bin
just taking up space in between the files you actually may want to keep there.

This tool allows you to configure file name matching regexes with an
associated minimum age, which will then be deleted from your trash bin when
the script is run.

# Requirements

* Python 3
* A Nextcloud account
* An application password for your account (please don't use your regular password!)
* `tqdm` package if you want progress bar support (`-C`/`--progress`)

# Example configuration

```
[Nextcloud]
; Base URL of the Nextcloud instance
url = https://nextcloud.example.com
username = 
; App password
password = 
; Maximum number of files to delete in one run
threshold = 50
; Minimum age of files in days before deletion
minimum_age = 30

[Joplin_timeCheck]
pattern = timeCheck.*\.txt
; minimum_age is inherited from [Nextcloud] section

[Android_Trashbin]
pattern = ^\.Trashed-
minimum_age = 0
```

This configuration will:
* delete files matching `timeCheck*.txt` after they've been deleted for 30 days.
* delete files matching `^.Trashed-` right away.

# Caveats

WebDAV can be very slow. There are numerous bugs filed at Nextcloud, many to
do with the amount of authentication tokens, but with mine all cleaned up,
it still takes 4-7 seconds for a WebDAV delete to go through, which is
possibly related to the amount of files in my trashbin, or not using a
memcache backend. Your initial script run may take hours, depending on how
many files need to be cleaned up.

# Development

The Github repository is a push mirror from my personal Gitlab instance.
Feel free to open issues or pull requests on Github. But it's perfect, no? ;-)
 
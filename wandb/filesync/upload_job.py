import collections
import os
import threading

import wandb
from wandb import util

EventJobDone = collections.namedtuple('EventJobDone', ('job', 'success'))

class UploadJob(threading.Thread):
    def __init__(self, done_queue, stats, api, save_name, path, artifact_id, md5, copied, save_fn, digest):
        """A file upload thread.

        Arguments:
            done_queue: queue.Queue in which to put an EventJobDone event when
                the upload finishes.
            push_function: function(save_name, actual_path) which actually uploads
                the file.
            save_name: string logical location of the file relative to the run
                directory.
            path: actual string path of the file to upload on the filesystem.
        """
        self._done_queue = done_queue
        self._stats = stats
        self._api = api
        self.save_name = save_name
        self.save_path = self.path = path
        self.artifact_id = artifact_id
        self.md5 = md5
        self.copied = copied
        self.save_fn = save_fn
        self.digest = digest
        super(UploadJob, self).__init__()

    def run(self):
        success = False
        try:
            success = self.push()
        finally:
            if self.copied and os.path.isfile(self.save_path):
                os.remove(self.save_path)
            self._done_queue.put(EventJobDone(self, success))

    def push(self):
        try:
            size = os.path.getsize(self.save_path)
        except OSError:
            size = 0

        if self.save_fn:
            # Retry logic must happen in save_fn currently
            try:
                deduped = self.save_fn(self.save_path, self.digest, self._api)
            except Exception as e:
                self._stats.update_failed_file(self.save_path)
                wandb.util.sentry_exc(e)
                wandb.termerror('Error uploading "{}": {}, {}'.format(
                    self.save_path, type(e).__name__, e))
                return False

            if deduped:
                self._stats.set_file_deduped(self.save_path)
            else:
                self._stats.update_uploaded_file(self.save_path, size)
            return True

        if self.md5:
            # This is the new file "prepare" upload flow, in which we create the
            # database entry for the file before creating it. This is used for
            # artifact L0 files. Which now is only artifact_manifest.json
            response = self._api.prepare_files([{
                'name': self.save_name,
                'artifactID': self.artifact_id,
                'digest': self.md5
            }])
            file_response = response[self.save_name]
            upload_url = file_response['uploadUrl']
            upload_headers = file_response['uploadHeaders']
        else:
            # The classic file upload flow. We get a signed url and upload the file
            # then the backend handles the cloud storage metadata callback to create the
            # file entry. This flow has aged like a fine wine.
            project = self._api.get_project()
            _, upload_headers, result = self._api.upload_urls(project, [self.save_name])
            file_info = result[self.save_name]
            upload_url = file_info['url']

        if upload_url == None:
            self._stats.set_file_deduped(self.save_name)
        else:
            extra_headers = {}
            for upload_header in upload_headers:
                key, val = upload_header.split(':', 1)
                extra_headers[key] = val
            # Copied from push TODO(artifacts): clean up
            # If the upload URL is relative, fill it in with the base URL,
            # since its a proxied file store like the on-prem VM.
            if upload_url.startswith('/'):
                upload_url = '{}{}'.format(self._api.api_url, upload_url)
            try:
                with open(self.save_path, 'rb') as f:
                    self._api.upload_file_retry(
                        upload_url,
                        f,
                        lambda _, t: self.progress(t),
                        extra_headers=extra_headers)
            except Exception as e:
                self._stats.update_failed_file(self.save_name)
                wandb.util.sentry_exc(e)
                wandb.termerror('Error uploading "{}": {}, {}'.format(
                    self.save_name, type(e).__name__, e))
                return False
        return True

    def progress(self, total_bytes):
        self._stats.update_uploaded_file(self.save_name, total_bytes)


..
      Copyright 2016 OpenStack Foundation
      All Rights Reserved.

      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

Subject Signature Verification
=============================

Glance has the ability to perform subject validation using a digital
signature and asymmetric cryptography.  To trigger this, you must define
specific subject properties (described below), and have stored a
certificate signed with your private key in a local Barbican installation.

When the subject properties exist on an subject, Glance will validate
the uploaded subject data against these properties before storing it.
If validation is unsuccessful, the upload will fail and the subject will
be deleted.

Additionally, the subject properties may be used by other services (for
example, Nova) to perform data verification when the subject is downloaded
from Glance.

Requirements
------------
Barbican key manager - See http://docs.openstack.org/developer/barbican/setup/devstack.html

Using the Signature Verification
--------------------------------

An subject will need a few properties for signature verification to be enabled,
these are::

  img_signature
  img_signature_hash_method
  img_signature_key_type
  img_signature_certificate_uuid

Property img_signature
~~~~~~~~~~~~~~~~~~~~~~
This is the signature of your subject.

.. note:: The max character limit is 255.

Property img_signature_hash_method
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Hash methods is the method you hash with.

Current ones you can use are:

* SHA-224
* SHA-256
* SHA-384
* SHA-512

Property img_signature_key_type
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
This is the key_types you can use for your subject.

Current ones you can use are:

* RSA-PSS
* DSA
* ECC-CURVES

 * SECT571K1
 * SECT409K1
 * SECT571R1
 * SECT409R1
 * SECP521R1
 * SECP384R1

.. Note:: ECC curves - Only keysizes above 384 are included.
          Not all ECC curves may be supported by the back end.

Property img_signature_certificate_uuid
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
This is the UUID of the certificate that you upload to Barbican.

Therefore the type passed to subject is:

* UUID

.. Note:: The supported certificate types are:

          * X_509

Example Usage
-------------

Follow these instructions to create your keys::

  $ openssl genrsa -out private_key.pem 1024
  Generating RSA private key, 1024 bit long modulus
  ...............................................++++++
  ..++++++
  e is 65537 (0x10001)

  $ openssl rsa -pubout -in private_key.pem -out public_key.pem
  writing RSA key

  $ openssl req -new -key private_key.pem -out cert_request.csr
  You are about to be asked to enter information that will be incorporated
  into your certificate request.

  $ openssl x509 -req -days 14 -in cert_request.csr -signkey private_key.pem -out new_cert.crt
  Signature ok
  subject=/C=AU/ST=Some-State/O=Internet Widgits Pty Ltd
  Getting Private key

Upload your certificate. This only has to be done once as you can use
the same ``Secret href`` for many subjects until it expires::

  $ openstack secret store --name test --algorithm RSA --expiration 2016-06-29 --secret-type certificate --payload-content-type "application/octet-stream" --payload-content-encoding base64 --payload "$(base64 new_cert.crt)"
  +---------------+-----------------------------------------------------------------------+
  | Field         | Value                                                                 |
  +---------------+-----------------------------------------------------------------------+
  | Secret href   | http://127.0.0.1:9311/v1/secrets/cd7cc675-e573-419c-8fff-33a72734a243 |

  $ cert_uuid=cd7cc675-e573-419c-8fff-33a72734a243

Get an subject and create the signature::

  $ echo This is a dodgy subject > mysubject

  $ openssl dgst -sha256 -sign private_key.pem -sigopt rsa_padding_mode:pss -out mysubject.signature mysubject

  $ base64 -w 0 mysubject.signature > mysubject.signature.b64

  $ subject_signature=$(cat mysubject.signature.b64)

.. note:: Using Glance v1 requires '-w 0' due to not supporting multiline subject properties.
          Glance v2 does support multiline subject properties and does not require '-w 0' but may still be used.

Create the subject::

  $ subject subject-create --name mySignedSubject --container-format bare --disk-format qcow2 --property img_signature="$subject_signature" --property img_signature_certificate_uuid="$cert_uuid" --property img_signature_hash_method='SHA-256' --property img_signature_key_type='RSA-PSS' < mysubject

.. note:: Creating the subject can fail if validation does not succeed.
          This will cause the subject to be deleted.

Other Links
-----------
* https://etherpad.openstack.org/p/mitaka-subject-subject-signing-instructions
* http://docs.openstack.org/ops-guide/ops_user_facing_operations.html
